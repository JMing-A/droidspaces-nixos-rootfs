# Droidspaces NixOS rootfs 构建仓库

用 GitHub Actions 手动构建 **NixOS rootfs 压缩包**，发布为 GitHub Release，并自动维护
`rootfs.json` 索引，供 [Droidspaces](https://github.com/ravindu644/Droidspaces-OSS) 直接读取使用。

整个仓库自带 NixOS 定义（`flake.nix` + `nix/`），**不依赖任何外部仓库**，上游挂了也照样能出包。

---

## 一、为什么需要这个仓库

Droidspaces 自己的 rootfs 构建仓库曾经在 CI 里跑过 NixOS，后来被删了。过程如下：

| 时间 | 事件 |
|---|---|
| 2026-05-18 | 上游首次引入 `build-nixos` job，用 `nix build github:ravindu644/Droidspaces-OSS#...` 出包 |
| 2026-05-20 | 同一条链路扩展到 3 个变体；systemd v259 那条只活了 33 小时就被换成 v257（实际构建不过） |
| 2026-09-09 | 上游把构建流程重构成「Dockerfile LABEL 驱动」（commit `a372bd4`），NixOS 无法用 Dockerfile 表达，**整个 NixOS 构建链被删除** |
| 2026-09-12 | 上游 `bf2aa0b` 把 journald 配置改成 `services.journald.settings.Journal`，但它 pin 的 nixpkgs 里根本没这个选项 |
| 本仓库 | 把 NixOS 构建链重建为独立流水线，并自建 flake，不再受上游影响 |

两个直接影响本仓库设计的历史教训：

1. **不要跨 nixpkgs 引用模块**。上游 `services.journald.settings does not exist` 就是这么来的：
   模块按新 nixpkgs 写，flake 却 pin 了旧 nixpkgs。本仓库只用**一个** nixpkgs 输入。
2. **`nix build --out-link ./result` 产出的是 symlink**。`find ./result -type f` 不会进入软链，
   会导致「包已经构建成功却报 0 个文件」。本仓库统一用 `find -L` 和 `cp -L`。

---

## 二、工作原理

```
手动点击 Run workflow
        │
        ▼
  ┌───────────┐  读 variants.json × systems.json
  │   plan    │  校验表格 → 算出 tag → 生成 build matrix
  └─────┬─────┘
        │ matrix（每个 system × 每个 variant 一个 job）
        ▼
  ┌───────────┐  安装 Nix → 恢复 /nix 缓存
  │   build   │  nix build <flake>#legacyPackages.<system>.nixosRootfsTarballs.<variant>
  └─────┬─────┘  重命名成 <file>-Droidspaces-rootfs-<arch>-<日期>-<tag>.tar.xz
        │        上传为 artifact
        ▼
  ┌───────────┐  下载全部 artifact → 算 SHA256 → 生成 rootfs.json
  │  release  │  创建 GitHub Release → 把 rootfs.json 提交回主分支
  └───────────┘
```

三个 job 的职责边界：

| job | 跑在 | 干什么 | 失败会怎样 |
|---|---|---|---|
| `plan` | `ubuntu-latest` | 校验 `variants.json` / `systems.json`，解析 tag，输出 matrix | 全部停下 |
| `build` | 每个矩阵项自己的 runner | 构建单个 rootfs 并上传 artifact | 同组继续（`fail-fast: false`），但 release 会被挡住 |
| `release` | `ubuntu-latest` | 生成 `rootfs.json`、建 Release、回写索引 | 已构建的包留在 artifact 里 |

---

## 三、快速开始

1. 打开仓库的 **Actions** 标签页
2. 左侧选 **Build NixOS rootfs**
3. 右侧点 **Run workflow**，按需填参数（见下表）
4. 等 5～15 分钟，到 **Releases** 页面下包

### 参数说明

| 参数 | 默认值 | 说明 |
|---|---|---|
| `variants` | `all` | 要构建的变体。填 `all`，或逗号分隔的 id，如 `minimal`、`minimal,minimal-tools` |
| `systems` | `all` | 目标架构。填 `all`，或 `aarch64-linux` / `x86_64-linux` |
| `include_experimental` | `true` | 是否包含 `variants.json` 里标了 `experimental: true` 的变体 |
| `publish` | `true` | 关掉就只构建、只留 artifact，**不建 Release、不改 `rootfs.json`**。调试构建用 |
| `tag` | 空 | Release 标签。空则用当前 UTC 时间 `vYYYYMMDD-HHMMSS`；填 `smoke` 这类自定义值也可以 |
| `flake_repo` | 空 | 覆盖 flake 来源。空则用**本仓库当前 commit** |
| `flake_ref` | 空 | 配合 `flake_repo` 用的分支/标签。空则用默认分支 |

### 只想试一下构建能不能过

```
variants = minimal
systems  = aarch64-linux
publish  = false
```

这样只跑 1 个 job，不产出 Release，也不会把 `rootfs.json` 覆盖成只有 1 条。

---

## 四、构建变体

| id | 名称 | 包含什么 | 预期体积 |
|---|---|---|---|
| `minimal` | NixOS - 最小镜像 | systemd、bash、coreutils、findutils、grep、sed、gawk、tar、gzip、xz、less、nano | 约 200 MB |
| `minimal-tools` | NixOS - 最小镜像（带常用工具） | 上面的全部 + git、curl、wget、procps、iproute2、iputils、which、openssh、cacert | 约 250 MB |

两个变体都基于 `virtualisation/lxc-container.nix`，都能在 Droidspaces 里正常开机。
要求宿主内核 **5.10 及以上**（systemd 需要新版内核的部分特性）。

### 自己加一个变体

三步，不需要改任何脚本：

1. `nix/my-variant.nix` —— 写一个 NixOS 模块（最简就是一个 `{ pkgs, ... }: { ... }`）
2. `flake.nix` 里的 `profiles` 加一行：`my-variant = ./nix/my-variant.nix;`
3. `variants.json` 加一条，`output` 填 `nixosRootfsTarballs`，`attr` 填 `my-variant`

然后 `python3 scripts/gen_rootfs_json.py --lint` 验证表格没问题。

---

---

## 四之二、内置账号与 SSH

每个变体都**默认开启 SSH 服务**，不需要额外配置：

| 项目 | 值 |
|---|---|
| SSH 端口 | `22`（容器内端口，App 侧做端口映射到手机） |
| 允许登录方式 | 密码登录（`PasswordAuthentication yes`） |
| root 登录 | 允许（`PermitRootLogin yes`） |
| PAM | 关闭（容器内无 PAM，用 `/etc/shadow` 原生校验） |
| 内置普通用户 | `nixos` |
| 用户密码 | 见仓库所有者提供的部署信息，首次登录后请立刻修改 |
| 用户属组 | `wheel`、`aid_inet`、`aid_net_raw`、`input`、`video`、`tty` |

关于 `aid_inet` / `aid_net_raw`：这两个是 Android 内核特有的组。不加它们，容器里的普通用户
**建不了 socket、发不了原始包**，表现就是 `ping` 和 `curl` 全部失败。这是最容易踩的坑。

首次登录后建议改密码：

```sh
# 以 root，或 nixos（带 sudo）登录后
passwd nixos
```

密码以 SHA-512 crypt 哈希形式固化在 `nix/base.nix`，不会以明文渲染进镜像。
要换密码，重新生成一个哈希并替换该文件里的 `hashedPassword`：

```sh
openssl passwd -6 -salt nixosrootfs '你的新密码'
```

仓库里存的是哈希不是明文，但**哈希本身也是敏感信息**，不要贴到公开 issue 里。

## 五、产出物：rootfs.json

每次发布都会重新生成，**不要手改**。它是一个数组，每一项对应一个压缩包：

| 字段 | 含义 |
|---|---|
| `name` | 显示名，如 `NixOS - 最小镜像` |
| `distro` | 发行版，固定 `NixOS` |
| `description` | 中文描述 |
| `architecture` | `aarch64` 或 `x86_64` |
| `file` | 变体文件名前缀 |
| `download_url` | 压缩包直链 |
| `sha256` | 压缩包 SHA256，用于校验 |
| `size_bytes` | 字节数 |
| `version` | Release 标签，如 `v20261111-190911` |
| `build_date` | 构建日期 `YYYYMMDD` |

Droidspaces App 读这个文件就知道有哪些镜像、从哪里下、下完怎么校验。

---

## 六、常见问题

**Q：构建失败了怎么办？**
先看失败 job 的日志。NixOS 求值失败通常在日志里有 `error:` 开头的一段，会指明是哪个选项有问题。
历史踩过的坑：`services.journald.settings does not exist`（跨 nixpkgs 引用）、
`expected exactly one .tar.xz under ./result, found 0`（软链未被跟随）。两者本仓库都已规避。

**Q：能本地构建吗？**
能，只要本机有 `nix` 且开启 flakes：

```sh
nix build github:JMing-A/droidspaces-nixos-rootfs#legacyPackages.aarch64-linux.nixosRootfsTarballs.minimal
ls result/tarball/
```

注意 `result` 是软链，查看内容要用 `ls result/` 或 `find -L result/`。

**Q：多久跑一次？**
不自动跑。这个仓库只有 `workflow_dispatch`，**只有你手动点才会构建**。
好处是不会有半夜被上游变动搞挂的流水线。

**Q：为什么不用 tag 而用 commit sha 做 flake 引用？**
为可复现。用分支名的话，你排队等 20 分钟的这期间别人推一个新 commit，构建出来的东西就不是你以为的那个了。用 sha 锁定本次运行的代码。

**Q：为什么改了 `rootfs.json` 会被自动提交？**
那是 `release` job 干的，用于把最新资产写回索引。如果同时有人在改，脚本会自动 rebase 重试 3 次。

---

## 七、仓库结构

```
flake.nix                                  自建 flake，输出 nixosRootfsTarballs.<variant>
nix/base.nix                               公共容器适配模块
nix/minimal.nix                            最小变体
nix/minimal-tools.nix                      带工具变体
variants.json                              变体表（驱动 matrix、索引、Release 说明）
systems.json                               system → 架构 + runner
scripts/plan_build.py                      参数 → build matrix
scripts/gen_rootfs_json.py                 资产 → rootfs.json（带 --lint）
scripts/write_notes.py                     rootfs.json → Release 说明
.github/workflows/build-nixos-rootfs.yml   手动构建 + 发布
rootfs.json                                自动生成，勿手改
docs/架构说明.md                            面向二次开发者
docs/使用指南.md                            面向普通用户
```

---

## 八、许可证

GPL-3.0，与上游 Droidspaces-OSS 一致。构建出的 rootfs 内部各软件有自己的许可证。
