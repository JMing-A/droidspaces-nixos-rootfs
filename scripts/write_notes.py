#!/usr/bin/env python3
"""Render the GitHub release notes from the rootfs.json written by this run."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rootfs-json", type=Path, default=Path("rootfs.json"))
    parser.add_argument("--out", type=Path, default=Path("notes.md"))
    parser.add_argument("--flake", required=True, help="flake reference that was built")
    parser.add_argument("--ref", default="main")
    parser.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID", "local"))
    args = parser.parse_args()

    entries = json.loads(args.rootfs_json.read_text(encoding="utf-8"))
    commit = os.environ.get("GITHUB_SHA", "")

    lines = [
        f"NixOS rootfs images for Droidspaces, built from `{args.flake}` at `{args.ref}`.",
        "",
    ]
    if commit:
        lines.append(f"Workflow run `{args.run_id}` on commit `{commit}`.")
    else:
        lines.append(f"Workflow run `{args.run_id}`.")

    lines += [
        "",
        "| name | architecture | size | file |",
        "|---|---|---|---|",
    ]
    for entry in entries:
        size_mib = entry["size_bytes"] / (1024 * 1024)
        filename = entry["download_url"].rsplit("/", 1)[-1]
        lines.append(f"| {entry['name']} | {entry['architecture']} | {size_mib:.1f} MiB | `{filename}` |")

    lines += [
        "",
        "Install with the Droidspaces app, or point it at the `rootfs.json` in this repository.",
        "",
    ]

    args.out.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {args.out} ({len(entries)} entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
