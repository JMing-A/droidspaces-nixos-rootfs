#!/usr/bin/env python3
"""Turn the workflow_dispatch inputs into a build plan.

Writes GitHub Actions outputs (tag, build_date, flake_base, matrix, counts) so the
build job can consume the matrix directly with fromJSON().
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def fail(message: str) -> "NoReturn":
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail(f"missing {path}")
    except json.JSONDecodeError as exc:
        fail(f"{path} is not valid JSON: {exc}")


def select(items: list, selector: str, label: str, key: str) -> list:
    selector = (selector or "all").strip()
    if selector == "all":
        return items
    wanted = [part.strip() for part in selector.split(",") if part.strip()]
    known = {item[key] for item in items}
    unknown = [name for name in wanted if name not in known]
    if unknown:
        fail(f"unknown {label}: {', '.join(unknown)} (known: {', '.join(sorted(known))})")
    chosen = [item for item in items if item[key] in wanted]
    if not chosen:
        fail(f"{label} selection '{selector}' matched nothing")
    return chosen


def default_flake_reference() -> str:
    """github:<owner>/<repo>/<sha>.

    Pinning the commit that triggered the run keeps a build reproducible: later
    pushes cannot change what this run actually built.
    """
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    sha = os.environ.get("GITHUB_SHA", "").strip()
    if not repo or not sha:
        fail(
            "flake_repo is empty and GITHUB_REPOSITORY/GITHUB_SHA are not set; "
            "pass --flake-repo (and optionally --flake-ref) explicitly"
        )
    return f"github:{repo}/{sha}"


def join_flake(repo: str, ref: str) -> str:
    """Attach an optional ref to a flake reference prefix.

    github:owner/repo       -> ref appended, or left alone when ref is empty
    github:owner/repo/<rev> -> already pinned, the caller's ref is ignored
    path:/some/dir, git+... -> ref appended as ?ref=<ref>
    """
    repo = repo.strip().rstrip("/")
    ref = ref.strip()
    if not repo:
        fail("flake repo must not be empty")
    if repo.startswith("github:"):
        segments = [part for part in repo[len("github:") :].split("/") if part]
        if len(segments) < 2:
            fail(f"flake repo '{repo}' must look like github:owner/repo")
        if len(segments) > 2:
            if ref:
                print(
                    f"note: '{repo}' already pins a ref, ignoring flake_ref '{ref}'",
                    file=sys.stderr,
                )
            return repo
        return f"{repo}/{ref}" if ref else repo
    if not ref:
        return repo
    separator = "&" if "?" in repo else "?"
    return f"{repo}{separator}ref={ref}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variants", default="all", help="'all' or comma separated variant ids")
    parser.add_argument("--systems", default="all", help="'all' or comma separated systems")
    parser.add_argument(
        "--flake-repo",
        default="",
        help="flake reference prefix, e.g. github:owner/repo; empty means this repo at GITHUB_SHA",
    )
    parser.add_argument(
        "--flake-ref",
        default="",
        help="ref inside the flake repo; empty keeps whatever the repo reference implies",
    )
    parser.add_argument("--tag", default="", help="release tag override, vYYYYMMDD-HHMMSS")
    parser.add_argument("--include-experimental", default="true", help="'false' to skip experimental variants")
    parser.add_argument("--output", type=Path, required=True, help="path written in GITHUB_OUTPUT format")
    args = parser.parse_args()

    all_variants = load(REPO_ROOT / "variants.json")
    all_systems = load(REPO_ROOT / "systems.json")
    if not isinstance(all_variants, list) or not isinstance(all_systems, dict):
        fail("variants.json must be a list and systems.json an object")

    include_experimental = args.include_experimental.strip().lower() != "false"
    if not include_experimental:
        all_variants = [v for v in all_variants if not v.get("experimental")]

    variants = select(all_variants, args.variants, "variants", "id")
    systems = select(
        [dict(meta, system=name) for name, meta in all_systems.items()],
        args.systems,
        "systems",
        "system",
    )

    tag = args.tag.strip()
    if tag:
        if not tag.startswith("v"):
            tag = f"v{tag}"
    else:
        tag = datetime.now(timezone.utc).strftime("v%Y%m%d-%H%M%S")
    if not re.fullmatch(r"v[A-Za-z0-9][A-Za-z0-9._-]*", tag):
        fail(f"tag '{tag}' contains characters that are not safe in a release tag")
    # build_date keeps the file name shape the Droidspaces app expects; an
    # arbitrary tag (e.g. a smoke run) falls back to today's UTC date.
    head = tag[1:].split("-")[0]
    build_date = head if re.fullmatch(r"\d{8}", head) else datetime.now(timezone.utc).strftime("%Y%m%d")

    # The flake lives in this repository, so the default source is this commit.
    flake_repo = args.flake_repo.strip()
    flake_ref = args.flake_ref.strip()
    if not flake_repo:
        if flake_ref:
            print(
                f"note: flake_repo is empty, ignoring flake_ref '{flake_ref}'",
                file=sys.stderr,
            )
        base = default_flake_reference()
        effective_ref = base.rsplit("/", 1)[-1]
    else:
        base = join_flake(flake_repo, flake_ref)
        effective_ref = flake_ref

    matrix = {"include": []}
    for system in systems:
        for variant in variants:
            matrix["include"].append(
                {
                    "system": system["system"],
                    "arch": system["arch"],
                    "runner": system["runner"],
                    "variant_id": variant["id"],
                    "variant_name": variant["name"],
                    "file": variant["file"],
                    "output": variant["output"],
                    "attr": variant["attr"],
                    "experimental": bool(variant.get("experimental")),
                    # Single level: legacyPackages.<system>.<output>.<attr>.
                    "attr_path": f"legacyPackages.{system['system']}.{variant['output']}.{variant['attr']}",
                }
            )

    lines = {
        "tag": tag,
        "build_date": build_date,
        "flake_base": base,
        "flake_ref": effective_ref,
        "matrix": json.dumps(matrix, separators=(",", ":")),
        "job_count": str(len(matrix["include"])),
        "variant_count": str(len(variants)),
        "system_count": str(len(systems)),
        "experimental_count": str(sum(1 for v in variants if v.get("experimental"))),
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("a", encoding="utf-8") as handle:
        for key, value in lines.items():
            handle.write(f"{key}={value}\n")

    print(f"tag={tag} build_date={build_date} flake_base={base} jobs={len(matrix['include'])}")
    for entry in matrix["include"]:
        print(f"  {entry['system']:<14} {entry['variant_id']:<20} {entry['attr_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
