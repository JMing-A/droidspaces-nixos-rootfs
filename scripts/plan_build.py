#!/usr/bin/env python3
"""Turn the workflow_dispatch inputs into a build plan.

Writes GitHub Actions outputs (tag, build_date, matrix, counts) so the build job
can consume the matrix directly with fromJSON().
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variants", default="all", help="'all' or comma separated variant ids")
    parser.add_argument("--systems", default="all", help="'all' or comma separated systems")
    parser.add_argument("--flake-repo", required=True, help="flake reference prefix, e.g. github:owner/repo")
    parser.add_argument("--flake-ref", default="main", help="ref within the flake repo")
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

    flake_repo = args.flake_repo.strip().rstrip("/")
    flake_ref = (args.flake_ref or "main").strip()
    # github:owner/repo already defaults to the default branch, so only pin the
    # ref when the caller asked for something other than main.
    base = f"{flake_repo}/{flake_ref}" if flake_ref not in ("", "main") else flake_repo

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
                    "attr_path": f"legacyPackages.{system['system']}.{variant['output']}.{system['system']}.{variant['attr']}",
                }
            )

    lines = {
        "tag": tag,
        "build_date": build_date,
        "flake_base": base,
        "flake_ref": flake_ref,
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

    print(f"tag={tag} build_date={build_date} jobs={len(matrix['include'])}")
    for entry in matrix["include"]:
        print(f"  {entry['system']:<14} {entry['variant_id']:<20} {entry['attr_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
