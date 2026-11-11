#!/usr/bin/env python3
"""Regenerate rootfs.json from the release assets produced by a build run.

The schema matches what the Droidspaces app consumes: a flat list of entries
carrying name/distro/description/architecture/file/download_url/sha256/
size_bytes/version/build_date. Only the stdlib is used on purpose, so this runs
on a bare runner as well as locally.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
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


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_version(raw: str) -> str:
    version = raw.strip()
    if not version:
        fail("version is empty")
    if not version.startswith("v"):
        version = f"v{version}"
    if not re.fullmatch(r"v\d{8}-\d{6}", version):
        fail(f"version '{raw}' does not look like vYYYYMMDD-HHMMSS")
    return version


def build_entry(variant: dict, arch: str, tarball: Path, *, repo: str, version: str, build_date: str) -> dict:
    entry = {
        "name": variant["name"],
        "distro": variant["distro"],
        "description": variant["description"],
        "architecture": arch,
        "file": variant["file"],
        "download_url": f"https://github.com/{repo}/releases/download/{version}/{tarball.name}",
        "sha256": sha256_of(tarball),
        "size_bytes": tarball.stat().st_size,
        "version": version,
        "build_date": build_date,
    }
    for extra_key, extra_value in (variant.get("extra") or {}).items():
        entry[extra_key] = extra_value
    return entry


def collect(dist: Path, variants: list[dict], systems: dict, repo: str, version: str, build_date: str) -> tuple[list[dict], list[str]]:
    entries, missing = [], []
    for system, meta in systems.items():
        arch = meta["arch"]
        for variant in variants:
            tarball = dist / f"{variant['file']}-Droidspaces-rootfs-{arch}-{build_date}-{version}.tar.xz"
            if not tarball.is_file():
                missing.append(tarball.name)
                continue
            if not tarball.name.endswith(".tar.xz") or tarball.stat().st_size == 0:
                fail(f"{tarball} is not a usable tarball")
            entries.append(build_entry(variant, arch, tarball, repo=repo, version=version, build_date=build_date))
    entries.sort(key=lambda item: (item["architecture"], item["name"].lower()))
    return entries, missing


def lint(variants: list[dict], systems: dict) -> int:
    print(f"variants: {len(variants)}")
    for variant in variants:
        flag = "experimental" if variant.get("experimental") else "stable"
        print(f"  - {variant['id']:<20} {flag:<12} {variant['output']}.{variant['attr']}")
    print(f"systems:  {len(systems)}")
    for system, meta in systems.items():
        print(f"  - {system:<14} arch={meta['arch']:<8} runner={meta['runner']}")
    total = len(variants) * len(systems)
    print(f"entries per release: {total} ({total - len([v for v in variants if v.get('experimental')]) * len(systems)} stable)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, help="directory holding the built .tar.xz files")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "rootfs.json", help="where to write rootfs.json")
    parser.add_argument("--repo", default="", help="owner/name used to build download URLs")
    parser.add_argument("--version", default="", help="release tag, vYYYYMMDD-HHMMSS")
    parser.add_argument("--build-date", default="", help="release date, YYYYMMDD (defaults to the version)")
    parser.add_argument("--allow-partial", action="store_true", help="write the file even when some tarballs are missing")
    parser.add_argument("--variants", type=Path, default=DEFAULT_VARIANTS)
    parser.add_argument("--systems", type=Path, default=DEFAULT_SYSTEMS)
    parser.add_argument("--lint", action="store_true", help="validate the config files and exit")
    args = parser.parse_args()

    variants = load_variants(args.variants)
    systems = load_systems(args.systems)

    if args.lint:
        return lint(variants, systems)

    if not args.dist or not args.repo or not args.version:
        fail("--dist, --repo and --version are required unless --lint is used")

    version = parse_version(args.version)
    build_date = (args.build_date or version[1:].split("-")[0]).strip()
    if not re.fullmatch(r"\d{8}", build_date):
        fail(f"build date '{build_date}' must be YYYYMMDD")

    entries, missing = collect(args.dist, variants, systems, args.repo, version, build_date)
    if missing:
        listing = "\n  ".join(missing)
        if not args.allow_partial:
            fail(f"missing {len(missing)} expected tarball(s):\n  {listing}")
        print(f"warning: {len(missing)} tarball(s) missing, writing a partial index:\n  {listing}", file=sys.stderr)

    if not entries:
        fail("no tarballs found, refusing to write an empty rootfs.json")

    args.out.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {args.out} with {len(entries)} entries for {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
