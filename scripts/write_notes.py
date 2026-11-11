#!/usr/bin/env python3
"""Render the GitHub release notes from the rootfs.json written by this run."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def human_size(num_bytes: int) -> str:
    return f"{num_bytes / (1024 * 1024):.1f} MiB"


def describe_source(flake: str, ref: str, commit: str, repo: str) -> str:
    """Turn the raw flake reference into something a reader understands.

    The default reference is path:/home/runner/work/<repo>/<repo>, which is a
    CI-internal location and meaningless in a release note. When that is the
    case, say "this repository at commit X" instead.
    """
    if flake.startswith("path:"):
        short = commit[:7] if commit else "未知"
        repo_part = repo or "本仓库"
        return f"本仓库 `{repo_part}`，commit `{short}`"
    if ref:
        return f"`{flake}`，ref `{ref}`"
    return f"`{flake}`"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rootfs-json", type=Path, default=Path("rootfs.json"))
    parser.add_argument("--out", type=Path, default=Path("notes.md"))
    parser.add_argument("--flake", required=True, help="flake reference that was built")
    parser.add_argument("--ref", default="")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID", "local"))
    args = parser.parse_args()

    entries = json.loads(args.rootfs_json.read_text(encoding="utf-8"))
    commit = os.environ.get("GITHUB_SHA", "")

    source = describe_source(args.flake, args.ref, commit, args.repo)
    run_ref = f"[`{args.run_id}`](https://github.com/{args.repo}/actions/runs/{args.run_id})" if args.repo else f"`{args.run_id}`"

    lines = [
        "## NixOS rootfs 镜像",
        "",
        "适用于 [Droidspaces](https://github.com/ravindu644/Droidspaces-OSS) 容器运行时的 NixOS 根文件系统。",
        "",
        "| 项目 | 值 |",
        "|---|---|",
        f"| 构建来源 | {source} |",
        f"| 工作流运行 | {run_ref} |",
        f"| 镜像数量 | {len(entries)} |",
        "",
        "### 包含的镜像",
        "",
        "| 镜像 | 架构 | 大小 | SHA256（前 16 位） |",
        "|---|---|---|---|",
    ]

    for entry in entries:
        lines.append(
            "| {name} | {arch} | {size} | `{sha}` |".format(
                name=entry["name"],
                arch=entry["architecture"],
                size=human_size(entry["size_bytes"]),
                sha=entry["sha256"][:16],
            )
        )

    lines += [
        "",
        "### 怎么用",
        "",
        "1. 按手机架构下载上表中的 `.tar.xz`（绝大多数 Android 手机是 `aarch64`）",
        "2. 在 Droidspaces App 里选择「从本地 rootfs 导入」，选中下载的文件",
        "3. 分配至少 4 GB 磁盘后启动",
        "",
        "每个镜像旁边都有对应的 `SHA256SUMS-*.txt`，可用 `sha256sum -c` 校验完整性。",
        "",
        "### 默认配置",
        "",
        "| 项目 | 值 |",
        "|---|---|",
        "| SSH | 已开启，监听 22 端口 |",
        "| 登录方式 | 密码登录，允许 root |",
        "| 内置用户 | `nixos`（在 `wheel` 组，可用 sudo） |",
        "| Nix | 已启用 flakes，`wheel` 成员为 trusted-users |",
        "| 内核要求 | 5.10 及以上 |",
        "",
        "首次登录后请立刻用 `passwd nixos` 修改密码。",
        "",
        "---",
        "",
        "`rootfs.json` 已同步更新，Droidspaces 可直接读取该索引获取下载地址与校验值。",
        "",
    ]

    args.out.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {args.out} ({len(entries)} entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())