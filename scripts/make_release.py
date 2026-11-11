#!/usr/bin/env python3
"""Create or verify the release that the build jobs will upload into.

The workflow uploads tarballs straight to the release, so the release has to
exist before any parallel build job finishes. Creating it here also means the
release page appears immediately instead of after the last variant.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, text=True, capture_output=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--body", default="")
    args = parser.parse_args()

    if not args.repo:
        print("error: --repo is required", file=sys.stderr)
        return 1

    body = args.body or (
        "NixOS rootfs 镜像构建中，完成前该页面只包含部分资产。\n\n"
        "最终清单与校验值见本仓库的 `rootfs.json`。\n"
    )

    probe = run(["gh", "release", "view", args.tag, "--repo", args.repo])
    if probe.returncode == 0:
        print(f"release {args.tag} already exists")
        # Refresh the placeholder body so a rerun does not keep stale text.
        run(
            [
                "gh", "release", "edit", args.tag,
                "--repo", args.repo,
                "--notes", body,
            ]
        )
        return 0

    created = run(
        [
            "gh", "release", "create", args.tag,
            "--repo", args.repo,
            "--title", f"NixOS rootfs {args.tag}",
            "--notes", body,
            "--latest",
        ]
    )
    if created.returncode != 0:
        print(f"error: gh release create failed\n{created.stderr}", file=sys.stderr)
        return 1

    print(f"created release {args.tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())