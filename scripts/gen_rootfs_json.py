#!/usr/bin/env python3
"""Regenerate rootfs.json from the assets attached to a GitHub release.

The schema matches what the Droidspaces app consumes: a flat list of entries
carrying name/distro/description/architecture/file/download_url/sha256/
size_bytes/version/build_date.

Assets are read from the release API rather than from a local directory,
because the build jobs upload straight to the release. GitHub returns the
sha256 digest of each asset, so nothing has to be downloaded to hash it.
Only the stdlib is used on purpose.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_VARIANTS = REPO_ROOT / "variants.json"
DEFAULT_SYSTEMS = REPO_ROOT / "systems.json"
REQUIRED_KEYS = ("id", "name", "file", "distro", "description", "output", "attr")


def fail(message: str) -> "NoReturn":
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail(f"missing {path}")
    except json.JSONDecodeError as exc:
        fail(f"{path} is not valid JSON: {exc}")


def load_variants(path: Path) -> list[dict]:
    variants = load_json(path)
    if not isinstance(variants, list) or not variants:
        fail(f"{path} must be a non-empty list")
    seen_ids, seen_files = set(), set()
    for index, variant in enumerate(variants):
        for key in REQUIRED_KEYS:
            if not variant.get(key):
                fail(f"{path}[{index}] is missing '{key}'")
        if variant["id"] in seen_ids:
            fail(f"duplicate variant id '{variant['id']}'")
        seen_ids.add(variant["id"])
        if variant["file"] in seen_files:
            fail(f"duplicate variant file '{variant['file']}'")
        seen_files.add(variant["file"])
        if not isinstance(variant.get("experimental", False), bool):
            fail(f"{path}[{index}] 'experimental' must be a boolean")
    return variants


def load_systems(path: Path) -> dict:
    systems = load_json(path)
    if not isinstance(systems, dict) or not systems:
        fail(f"{path} must be a non-empty object")
    for system, meta in systems.items():
        for key in ("arch", "runner"):
            if not meta.get(key):
                fail(f"{path}['{system}'] is missing '{key}'")
    return systems


def parse_version(raw: str) -> str:
    version = raw.strip()
    if not version:
        fail("version is empty")
    if not version.startswith("v"):
        version = f"v{version}"
    if not re.fullmatch(r"v\d{8}-\d{6}", version):
        fail(f"version '{raw}' does not look like vYYYYMMDD-HHMMSS")
    return version


def fetch_release_assets(repo: str, tag: str, token: str) -> dict:
    """Return {asset name: asset dict} for the given release."""
    url = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
    request = urllib.request.Request(url)
    request.add_header("Accept", "application/vnd.github+json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            release = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        fail(f"cannot read release {tag}: HTTP {exc.code} {exc.reason}")
    assets = release.get("assets") or []
    return {asset["name"]: asset for asset in assets}


def asset_digest(asset: dict) -> str:
    """GitHub reports sha256 as 'sha256:<hex>' in `digest`."""
    digest = (asset.get("digest") or "").strip()
    if digest.startswith("sha256:"):
        return digest.split(":", 1)[1]
    return ""


def build_entry(variant: dict, arch: str, asset: dict, *, repo: str, version: str, build_date: str) -> dict:
    return {
        "name": variant["name"],
        "distro": variant["distro"],
        "description": variant["description"],
        "architecture": arch,
        "file": variant["file"],
        "download_url": asset["browser_download_url"],
        "sha256": asset_digest(asset),
        "size_bytes": asset["size"],
        "version": version,
        "build_date": build_date,
    }


def collect(assets: dict, variants: list[dict], systems: dict, repo: str, version: str, build_date: str):
    entries, missing = [], []
    for system, meta in systems.items():
        if not meta.get("enabled", True):
            continue
        arch = meta["arch"]
        for variant in variants:
            name = f"{variant['file']}-Droidspaces-rootfs-{arch}-{build_date}-{version}.tar.xz"
            asset = assets.get(name)
            if not asset:
                missing.append(name)
                continue
            if not asset_digest(asset):
                fail(f"asset {name} has no sha256 digest; GitHub may not have finished hashing it")
            entries.append(build_entry(variant, arch, asset, repo=repo, version=version, build_date=build_date))
    entries.sort(key=lambda item: (item["architecture"], item["name"].lower()))
    return entries, missing


def lint(variants: list[dict], systems: dict) -> int:
    print(f"variants: {len(variants)}")
    for variant in variants:
        flag = "experimental" if variant.get("experimental") else "stable"
        print(f"  - {variant['id']:<20} {flag:<12} {variant['output']}.{variant['attr']}")
    print(f"systems:  {len(systems)}")
    enabled = []
    for system, meta in systems.items():
        state = "on " if meta.get("enabled", True) else "off"
        print(f"  - {system:<14} [{state}] arch={meta['arch']:<8} runner={meta['runner']}")
        if meta.get("enabled", True):
            enabled.append(system)

    experimental = len([v for v in variants if v.get("experimental")])
    total = len(variants) * len(enabled)
    stable = total - experimental * len(enabled)
    print(f"enabled systems: {len(enabled)} of {len(systems)}")
    print(f"entries per release: {total} ({stable} stable, {total - stable} experimental)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "rootfs.json", help="where to write rootfs.json")
    parser.add_argument("--repo", default="", help="owner/name of the repository holding the release")
    parser.add_argument("--tag", default="", help="release tag, vYYYYMMDD-HHMMSS")
    parser.add_argument("--build-date", default="", help="release date, YYYYMMDD (defaults to the tag)")
    parser.add_argument("--token", default=os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN", ""))
    parser.add_argument("--allow-partial", action="store_true", help="write the file even when some assets are missing")
    parser.add_argument("--variants", type=Path, default=DEFAULT_VARIANTS)
    parser.add_argument("--systems", type=Path, default=DEFAULT_SYSTEMS)
    parser.add_argument("--lint", action="store_true", help="validate the config files and exit")
    args = parser.parse_args()

    variants = load_variants(args.variants)
    systems = load_systems(args.systems)

    if args.lint:
        return lint(variants, systems)

    if not args.repo or not args.tag:
        fail("--repo and --tag are required unless --lint is used")

    version = parse_version(args.tag)
    build_date = (args.build_date or version[1:].split("-")[0]).strip()
    if not re.fullmatch(r"\d{8}", build_date):
        fail(f"build date '{build_date}' must be YYYYMMDD")

    assets = fetch_release_assets(args.repo, version, args.token)
    print(f"release {version} exposes {len(assets)} asset(s)")

    entries, missing = collect(assets, variants, systems, args.repo, version, build_date)
    if missing:
        listing = "\n  ".join(missing)
        if not args.allow_partial:
            fail(f"missing {len(missing)} expected asset(s):\n  {listing}")
        print(f"warning: {len(missing)} asset(s) missing, writing a partial index:\n  {listing}", file=sys.stderr)

    if not entries:
        fail("no matching assets found, refusing to write an empty rootfs.json")

    args.out.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {args.out} with {len(entries)} entries for {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())