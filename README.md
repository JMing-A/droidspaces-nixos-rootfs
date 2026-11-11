# Droidspaces NixOS rootfs 构建流水线

本仓库是一条**手动触发**的 GitHub Actions 流水线，用来把 NixOS 打包成 Droidspaces 可以直接导入的 rootfs 压缩包（`*.tar.xz`），发布成 GitHub Release，并同步生成索引文件 `rootfs.json`。

产物供 [Droidspaces](https://github.com/ravindu644/Droidspaces-OSS)（Android 上的容器运行时）使用。

| 项 | 值 |
|---|---|
| 输入 | 自建 flake（`flake.nix` + `nix/` 下的 NixOS 模块） |
| 产出 | 每变体 × 每架构一个 `.tar.xz` + `rootfs.json` + `SHA256SUMS-*.txt` |
| 触发方式 | 仅 `workflow_dispatch`（网页点按钮或 API 调用），不随 push / 定时 / PR 触发 |
| 许可证 | GPL-3.0 |

---

## 1. 项目简介

一句话：**把 NixOS 构建成 Android 容器可用的 rootfs 压缩包，并维护 Droidspaces App 读取的索引文件。**

NixOS 没有「装完就能打包」的发行版镜像概念，它的系统是 flake 里的求值结果。本仓库把「求值 → 构建 tarball → 改名 → 校验 → 发布 → 生成索引」这一串固定动作固化下来，变体表和架构表放在 JSON 里，加减变体只改数据不改流水线。

---

## 2. 为什么需要这个仓库

NixOS 的构建链路曾经在上游仓库里，后来因为上游重构被整段移除。下面按时间顺序说明，这既是本仓库存在的原因，也是踩过的坑。

### 2.1 2026-05：NixOS 曾进入上游 CI

上游（`ravindu644/Droidspaces-OSS`）在自己的 rootfs 构建仓库里加过 NixOS 任务，和 Debian / Ubuntu / Alpine 等发行版并列，用同一个 CI 模板产出。

### 2.2 2026-09：上游重构为「Dockerfile LABEL 驱动」，NixOS 被移除

上游把构建体系重构成「一个发行版 = 一个 Dockerfile + 一组 `droidspaces.*` LABEL」，由 LABEL 告诉构建器怎么打包、怎么设置启动命令、有哪些元数据。

NixOS 的系统是 flake 求值出来的，**没办法写成一个 Dockerfile**：没有 `FROM`、没有 `RUN apt install`，rootfs 内容由 `config.system.build.tarball` 产出。既然无法用 LABEL 描述，它就整个被删掉了（上游 commit `a372bd4`）。

NixOS 的需求没有消失，只是没有地方构建了。**本仓库就是把这条链路重建出来，做成一条独立、手动触发、自带 flake 定义的流水线。**

### 2.3 依赖上游 flake 的尝试失败，改为自建 flake

第一版流水线是「不自带 flake，直接引用上游 flake」。这条路走不通：

- 上游 `main`（commit `bf2aa0b`，2026-09-12）把 journald 配置改写成 `services.journald.settings.Journal`；
- 但它 pin 的 nixpkgs（`c6e5ca3`）里根本没有 `services.journald.settings` 这个选项；
- 结果每个变体都在求值阶段直接死掉：

```text
error: The option `services.journald.settings' does not exist.
```

这不是流水线的 bug，是上游 flake 自身的缺陷（流水线已经成功解析 flake、进入求值，才在 `config.system.build.tarball` 内部报错）。

**结论：本仓库从 0 自建 flake**（`flake.nix` + `nix/` 下的容器适配模块），输出形如：

```text
legacyPackages.<system>.nixosRootfsTarballs.<variant>
```

不再依赖上游 flake 的选项命名，也不受上游重构影响。

### 2.4 第一阶段流水线的 bug：`--out-link` 是软链，`find -type f` 数到 0 个文件

第一阶段流水线里，收集产物用的是：

```sh
find ./result -type f -name '*.tar.xz'
```

但 `nix build --out-link ./result` 产出的 `./result` 是**指向 `/nix/store/...` 的符号链接**，`find` 默认不跟随软链，于是找到 0 个 `.tar.xz`；构建明明成功，却在收集步骤报失败。

修正：加 `-L` 让 `find` 跟随软链。

```sh
find -L ./result -type f -name '*.tar.xz'
```

这一点在 [`docs/架构说明.md`](docs/架构说明.md) 里也记了一遍，改流水线时别退回去。

---

## 3. 工作原理

整条流水线只有三个 job：`plan` → `build`（矩阵并行）→ `release`。

```text
┌──────────────────────────────────────────────────────────────────────┐
│ ① 手动触发                                                           │
│    GitHub → Actions → Build NixOS rootfs → Run workflow              │
│    输入：variants / systems / include_experimental / publish /       │
│          tag / flake_repo / flake_ref                                │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ workflow_dispatch
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│ ② plan（ubuntu-latest，单 job，几十秒）                              │
│    - python3 scripts/gen_rootfs_json.py --lint                       │
│      → 校验 variants.json / systems.json 合法性                      │
│    - python3 scripts/plan_build.py                                   │
│      → 解析 tag（空则 vYYYYMMDD-HHMMSS，UTC）                        │
│      → 过滤 experimental                                              │
│      → 生成 matrix（variants 与 systems 的笛卡尔积）                  │
│      → 拼出 flake_base 与每个格子的 attr_path                        │
│    输出：tag / build_date / flake_base / matrix / 各种计数           │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ matrix JSON
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│ ③ build（矩阵并行，N = 变体数 × 架构数，每格一台 runner）            │
│    每个 job：                                                        │
│    - 安装 Determinate Nix（自带 flakes）                             │
│    - cache-nix-action 还原 /nix 缓存                                 │
│    - nix build <flake>#<attr_path> --out-link ./result               │
│    - find -L ./result 找唯一的 .tar.xz，改名为                       │
│      <file>-Droidspaces-rootfs-<arch>-<build_date>-<tag>.tar.xz      │
│    - sha256sum → dist/SHA256SUMS-<arch>-<file>.txt                   │
│    - upload-artifact（保留 7 天）                                    │
│    fail-fast: false —— 一个变体挂了不影响其他变体跑完                │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ 全部 build job 成功且 publish=true
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│ ④ release（ubuntu-latest，单 job）                                   │
│    - download-artifact 把所有 tarball 汇总到 dist/                   │
│    - gen_rootfs_json.py --allow-partial → rootfs.json                │
│      （重算 sha256 / size_bytes / download_url）                     │
│    - write_notes.py → notes.md，并写入 GITHUB_STEP_SUMMARY           │
│    - gh release create（已存在则 upload --clobber + edit --notes）   │
│    - 提交更新后的 rootfs.json 回默认分支（失败重试 3 次，带 rebase） │
└───────────────────────────────┬──────────────────────────────────────┘
                                ▼
                    Release 资产 + 仓库根目录 rootfs.json
```

三个 job 的职责边界、`--allow-partial` 的语义、缓存策略细节见 [`docs/架构说明.md`](docs/架构说明.md)。

### 3.1 关键设计

| 设计 | 原因 |
|---|---|
| 只允许 `workflow_dispatch` | 一次全量构建要跑十几台 runner、几十分钟到数小时，且会创建 Release 并提交仓库，不适合自动触发 |
| `concurrency: build-nixos-rootfs` | 同一时间只允许一条流水线在跑，避免两个 run 抢同一个 tag |
| `permissions: contents: write` | 只有 release job 需要写 Release 和推 `rootfs.json`，权限给到最小可用 |
| 矩阵由脚本生成而非 YAML 手写 | 变体表是数据，加减变体不用碰 workflow |
| flake ref 固定到 commit sha 或 tag | 分支名会动，同样的输入可能构建出不同内容，详见 `docs/架构说明.md` |

---

## 4. 快速开始

### 4.1 网页操作步骤

1. 打开本仓库页面，点顶部 **Actions**。
2. 左侧选择 **Build NixOS rootfs**。
3. 右侧点 **Run workflow**，选分支（通常是 `main`）。
4. 按需填输入项，不填就用默认值。**第一次建议先做冒烟测试**（见 4.3）。
5. 点绿色的 **Run workflow** 确认。
6. 依次观察 `plan` → `build` → `release` 三个 job。点进任意 job 可以看 `nix build` 的完整日志。

### 4.2 输入项说明

| 输入项 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `variants` | 字符串 | `all` | 要构建的变体。`all` 表示全部；也可以用逗号分隔的变体 id，例如 `minimal,minimal-tools`。id 必须存在于 `variants.json`，写错会在 plan 阶段直接失败并列出可用 id |
| `systems` | 字符串 | `all` | 要构建的架构。`all` 表示全部；也可以写 `aarch64-linux` 或 `x86_64-linux`（逗号分隔）。取值必须存在于 `systems.json` |
| `include_experimental` | 布尔 | `true` | 是否包含 `variants.json` 里标了 `"experimental": true` 的变体。设为 `false` 时这些变体不参与矩阵 |
| `publish` | 布尔 | `true` | 是否创建 GitHub Release 并提交 `rootfs.json`。设为 `false` 只构建并上传 Actions artifact（可下载、保留 7 天），不动 Release、不推仓库，纯构建测试用 |
| `tag` | 字符串 | 空 | Release 标签。留空自动生成 `vYYYYMMDD-HHMMSS`（UTC）。手填时若不以 `v` 开头会自动补上；标签里不能有空格、`/` 等不安全字符。注意：`build_date` 取标签中 `v` 后第一段的 8 位数字，否则回退为当天 UTC 日期 |
| `flake_repo` | 字符串 | `github:ravindu644/Droidspaces-OSS` | 提供 NixOS rootfs 定义的 flake 位置。自建 flake 落地后应改成本仓库，例如 `github:JMing-A/droidspaces-nixos-rootfs` |
| `flake_ref` | 字符串 | `main` | `flake_repo` 里的 ref（分支 / tag / commit sha）。正式发布前建议固定到 commit sha |

### 4.3 推荐先做冒烟测试

只构建一个变体、一个架构、不发布：

| 输入项 | 值 |
|---|---|
| `variants` | `minimal` |
| `systems` | `aarch64-linux` |
| `include_experimental` | `false` |
| `publish` | `false` |

这样只跑一台 runner，出错时日志短、好定位，也不会留下半成品 Release。

### 4.4 用 API 触发（没有 gh CLI 时）

```sh
curl -s -X POST \
  -H "Authorization: Bearer $GH_TOKEN" \
  -H 'Accept: application/vnd.github+json' \
  "https://api.github.com/repos/<owner>/<repo>/actions/workflows/build-nixos-rootfs.yml/dispatches" \
  -d '{"ref":"main","inputs":{"variants":"minimal","systems":"aarch64-linux","include_experimental":"false","publish":"false"}}'
```

返回 HTTP 204 表示已受理（没有响应体是正常的）。

---

## 5. 构建变体说明

变体表 `variants.json` 是唯一真源：矩阵、`rootfs.json`、Release notes 全部由它派生。**下面表格若与文件不一致，以 `variants.json` 为准**，本地可以用下面这条命令打印当前实际内容：

```sh
python3 scripts/gen_rootfs_json.py --lint
```

### 5.1 当前规划的变体

| id | 名称 | 包含什么 | 体积预期 |
|---|---|---|---|
| `minimal` | NixOS - Minimal | 最小可用系统：systemd、`nix`、核心 Unix 工具（coreutils / bash / util-linux 等）、容器适配模块（关闭不适用单元、设置容器友好默认值）；不含编辑器、编译链、桌面组件 | 约 120–200 MiB（压缩后） |
| `minimal-tools` | NixOS - Minimal Tools | `minimal` 的全部内容，外加日常排障工具（`curl`、`git`、`vim` 或 `nano`、`ps`、`iproute2`、`tar` / `xz` 等） | 约 250–400 MiB（压缩后） |

体积数字只是量级估计：实际大小取决于所 pin 的 nixpkgs 和 systemd 版本，以 Release 页面显示的 `size_bytes` 为准。

### 5.2 仓库快照中的历史变体（将被 5.1 替换）

在变体表切换到 `minimal` / `minimal-tools` 之前，`variants.json` 里是下面这些以 systemd 版本区分的老变体，属性名对应上游 flake。保留在此便于对照：

| id | flake 属性（`attr`） | 说明 | 状态 |
|---|---|---|---|
| `minimal` | `minimal` | systemd 版本跟随所 pin 的 nixpkgs | 稳定 |
| `minimal-v257` | `minimal-with-systemd-v257` | 单独的 nixpkgs 输入，携带 systemd v257 | 稳定 |
| `minimal-pinned-v257` | `minimal-with-pinned-systemd-v257` | 用默认 nixpkgs，把 systemd 覆盖为 v257，并关掉不需要的容器单元 | 稳定 |
| `minimal-v259` | `minimal-with-systemd-v259` | 携带 systemd v259 | 实验性（上游曾因构建失败移除该变体） |
| `finix-experimental` | `experimental` | 基于 finix 社区 flake 模块 | 实验性 |

关于「内核 5.10 及以上」的约束：上游变体名称里带 `Kernel-5.10-and-up`，因为 systemd 在更低版本内核上缺少所需特性。Droidspaces 的目标设备内核普遍高于 5.10，但更老的内核不保证可用。

### 5.3 变体字段含义

| 字段 | 含义 |
|---|---|
| `id` | 变体标识，`workflow_dispatch` 的 `variants` 输入用它做选择 |
| `name` | 展示名，写进 `rootfs.json` 的 `name` 和 Release notes |
| `file` | 文件名前缀，最终产物为 `<file>-Droidspaces-rootfs-<arch>-<build_date>-<tag>.tar.xz` |
| `distro` | 发行版名，写进 `rootfs.json` 的 `distro`（NixOS 变体都填 `NixOS`） |
| `description` | 一句话说明，写进 `rootfs.json` 的 `description` |
| `output` | flake 里的顶层输出名（如 `nixosRootfsTarballs`） |
| `attr` | 该输出下 `<system>` 内的属性名（如 `minimal`） |
| `experimental` | 布尔值。为 `true` 时受 `include_experimental` 开关控制 |

`attr_path` 由 `plan_build.py` 拼出来，格式固定为：

```text
legacyPackages.<system>.<output>.<system>.<attr>
```

---

## 6. 产出物

### 6.1 文件命名规则

```text
<file>-Droidspaces-rootfs-<arch>-<build_date>-<tag>.tar.xz
```

示例：

```text
NixOS-Minimal-Droidspaces-rootfs-aarch64-20261112-v20261112-030000.tar.xz
```

同目录下还有 `SHA256SUMS-<arch>-<file>.txt`（`sha256sum` 格式，可直接 `sha256sum -c` 校验）。

### 6.2 `rootfs.json` 字段

`rootfs.json` 由 `scripts/gen_rootfs_json.py` 从 release 资产自动生成，**不要手改**（每次发布都会被覆盖并提交回默认分支）。文件是一个**扁平数组**，每个元素对应「一个变体 × 一个架构」。

| 字段 | 类型 | 含义 |
|---|---|---|
| `name` | string | 展示名，来自 `variants.json` 的 `name` |
| `distro` | string | 发行版名，NixOS 变体为 `NixOS` |
| `description` | string | 说明文字，来自 `variants.json` |
| `architecture` | string | 架构，`aarch64` 或 `x86_64` |
| `file` | string | 文件名前缀（不含架构、日期、标签、扩展名） |
| `download_url` | string | 完整下载地址，指向对应 Release 里的 tarball |
| `sha256` | string | 该 tarball 的 SHA256（生成时现场计算，不读旧值） |
| `size_bytes` | int | 字节数 |
| `version` | string | Release 标签，`vYYYYMMDD-HHMMSS` |
| `build_date` | string | 构建日期，`YYYYMMDD` |

条目按 `architecture`、`name` 排序。示例：

```json
[
  {
    "name": "NixOS - Minimal",
    "distro": "NixOS",
    "description": "Minimal NixOS rootfs with basic packages.",
    "architecture": "aarch64",
    "file": "NixOS-Minimal",
    "download_url": "https://github.com/<owner>/<repo>/releases/download/v20261112-030000/NixOS-Minimal-Droidspaces-rootfs-aarch64-20261112-v20261112-030000.tar.xz",
    "sha256": "64 位十六进制字符串",
    "size_bytes": 157286400,
    "version": "v20261112-030000",
    "build_date": "20261112"
  }
]
```

### 6.3 Droidspaces App 怎么用它

1. App 读取 `rootfs.json`，按 `architecture` 过滤出与本机匹配的条目；
2. 用户选中一个条目，App 用 `download_url` 下载 tarball；
3. 下载完用 `sha256` 校验，不一致则拒绝导入；
4. 校验通过后用 `file` / `name` / `distro` / `description` 展示信息，并解压成容器 rootfs。

也就是说：**`rootfs.json` 是 App 与 Release 资产之间的唯一契约**。构建成功但 `rootfs.json` 没更新，App 里就看不到新包；`rootfs.json` 更新了但资产被删，下载会 404。

---

## 7. 常见问题

### 7.1 构建为什么失败？

按 job 分层看，失败点只有几类：

| 失败阶段 | 典型报错 | 原因与处理 |
|---|---|---|
| `plan` | `unknown variants: xxx (known: ...)` | `variants` 输入写了不存在的 id。按报错里列出的 `known` 改 |
| `plan` | lint 报错，例如 `is missing 'file'` | `variants.json` / `systems.json` 被改坏（缺字段、`id` 或 `file` 重复）。跑 `python3 scripts/gen_rootfs_json.py --lint` 定位 |
| `build` | `error: The option 'services.journald.settings' does not exist` | 引用了选项与 nixpkgs 不匹配的 flake ref。把 `flake_ref` 换到两者匹配的 commit 或 tag |
| `build` | `expected exactly one .tar.xz under ./result, found 0` | 收集步骤没找到产物。确认收集用的是 `find -L`（跟随 `./result` 软链）；看同步骤打印的 `find ./result -maxdepth 3 -type f` 调试输出 |
| `build` | job 被取消或超时 | 单 job 上限 `timeout-minutes: 350`。冷缓存加大闭包可能逼近上限，重跑通常能命中缓存 |
| `build` | `nix build` 求值错误 | 这是 flake 本身的问题，不是流水线问题：流水线能解析 flake 说明 ref 可达，错在模块求值 |
| `release` | `no tarballs to release` | `dist/` 为空，通常是所有 build 都失败了（`release` 需要 `build` 成功） |
| `release` | `could not push rootfs.json after 3 attempts` | 默认分支保护或并发提交导致推送失败，重试 3 次后报错。此时 Release 已创建，只是索引没提交，可重跑一次 |

补充：`build` 的 `fail-fast: false` 意味着**一个变体失败不会取消其他变体**，从失败的 job 名字就能看出是哪个「架构 / 变体」格子坏了；但 `release` 仍然要求全部 build 成功，所以坏变体会阻止发布。只想要健康变体时，把 `variants` 收窄后重跑。

### 7.2 能不能本地构建？

能，但门槛不低，且**本仓库默认不假设你有 Nix**。

本地构建单个属性：

```sh
nix build github:JMing-A/droidspaces-nixos-rootfs#legacyPackages.aarch64-linux.nixosRootfsTarballs.aarch64-linux.minimal
```

拿到 tarball 后再手动喂给索引生成脚本：

```sh
python3 scripts/gen_rootfs_json.py \
  --dist dist \
  --out rootfs.json \
  --repo <owner>/<repo> \
  --version v20261112-030000 \
  --allow-partial
```

限制：

- 需要 Linux 与 Nix（已启用 flakes），macOS 上构建 Linux rootfs 需要额外配置；
- 交叉架构（在 x86_64 上构建 aarch64）需要 binfmt / QEMU，速度很慢；
- PRoot 或容器环境里通常装不上 Nix，这类环境请走 CI。

### 7.3 多久跑一次？

**不会自动跑。** 触发方式只有 `workflow_dispatch`，没有 `schedule`、没有 `push`、没有 `pull_request`。

建议节奏：

- flake 里的 nixpkgs 更新后跑一次；
- 需要换 systemd 版本或再发一个 Droidspaces 兼容版本时跑；
- 改完流水线后跑一次冒烟（`publish: false`）。

### 7.4 为什么有时产物比上次大很多？

`rootfs.json` 与 Release 里的 `size_bytes` 是实测值。体积变化通常来自 nixpkgs 更新（systemd、glibc、闭包变化）或变体定义调整，不是流水线问题。

### 7.5 `publish: false` 的产物去哪了？

在对应 run 页面的 **Artifacts** 区域，名称为 `rootfs-<arch>-<variant_id>`，保留 **7 天**。过期即删，需要长期保存就 `publish: true` 发 Release。

---

## 8. 目录结构

```text
flake.nix                                  自建 flake，输出 legacyPackages.<system>.nixosRootfsTarballs.<variant>
nix/base.nix 等                            NixOS 模块定义（容器适配）
variants.json                              构建变体表（id/name/file/distro/description/output/attr/experimental）
systems.json                               system -> arch + CI runner
scripts/plan_build.py                      workflow_dispatch 输入 -> build matrix
scripts/gen_rootfs_json.py                 发布资产 -> rootfs.json（带 --lint）
scripts/write_notes.py                     rootfs.json -> release notes
.github/workflows/build-nixos-rootfs.yml   手动构建 + 发布
rootfs.json                                自动生成，勿手改
docs/架构说明.md                            流水线内部机制（面向二次开发者）
docs/使用指南.md                            下载、导入、校验、加变体（面向使用者）
```

---

## 9. 许可证

本仓库的流水线代码以 **GPL-3.0** 发布，与上游 [Droidspaces-OSS](https://github.com/ravindu644/Droidspaces-OSS) 保持一致，完整条款见 [`LICENSE`](LICENSE)。

注意：仓库里的构建脚本是 GPL-3.0；**它构建出来的 rootfs 镜像内含各自独立的软件与许可证**，那些软件的许可不受本仓库许可证覆盖。
