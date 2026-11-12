# Droidspaces 容器里跑 NixOS 的公共部分。
#
# 只写「必须」的东西。每条非必要选项都是求值或构建失败的一个机会，
# 而本仓库的 CI 是唯一验证手段，所以宁可少写。
{
  lib,
  pkgs,
  modulesPath,
  ...
}: {
  # 这一行把 NixOS 调成容器形态：boot.isContainer = true，
  # 去掉内核、initrd、bootloader 这些在容器里既没用又会报错的东西。
  imports = [
    "${modulesPath}/virtualisation/lxc-container.nix"
  ];

  # 容器里的默认主机名，用户可以在 App 里改。
  networking.hostName = lib.mkDefault "nixos";

  # Android 内核上 nftables/iptables 与宿主网络栈相互干扰，容器里直接关掉防火墙。
  networking.firewall.enable = lib.mkDefault false;

  # systemd-networkd 在大部分 Android 内核上拿不到可用接口，默认不开；
  # 需要网络时 App 侧会注入 droidspaces.env，或用 dhcpcd 手动拉。
  systemd.network.enable = lib.mkDefault false;

  # 容器里没有 TPM，也没有可写的 ESP，别让 systemd 等它们。
  boot.loader.grub.enable = lib.mkDefault false;
  boot.loader.systemd-boot.enable = lib.mkDefault false;

  # 文档闭包很大（几百 MB），对 rootfs 没意义。
  documentation.enable = lib.mkDefault false;
  documentation.nixos.enable = lib.mkDefault false;
  documentation.man.enable = lib.mkDefault false;

  # ----------------------------------------------------------------
  # Nix：默认启用 flakes
  # ----------------------------------------------------------------
  # channel 关掉：镜像里用不到，而且 nix-channel 会在启动时尝试联网。
  # flakes 不需要 channel，直接从 lock 里的 input 拉。
  nix.channel.enable = lib.mkDefault false;

  nix.settings = {
    # 这两项默认是关的，不打开的话 nix build / nix flake 会直接报
    # "experimental Nix feature 'flakes' is disabled"。
    experimental-features = ["nix-command" "flakes"];

    # 只有 trusted-users 里的用户才能改 substituters、sandbox、--impure 等
    # 受限设置。非 trusted 用户跑 nix build 会刷一堆
    # "ignoring the client-specified setting ..." 警告，改缓存源也会被忽略。
    # wheel 成员本来就能 sudo 到 root，把他们设为 trusted 不扩大攻击面。
    trusted-users = ["root" "@wheel"];
  };

  # 本地构建产生的路径与 substituters 已有路径做硬链接去重，省磁盘。
  nix.settings.auto-optimise-store = lib.mkDefault true;

  # 让 nix 命令在 PATH 里可用（root 与 nixos 用户都能直接跑 nix build）。
  # 只放 nix 本身；git 属于「常用工具」，由各变体自己决定要不要装。
  # 多个模块定义 systemPackages 会自动合并，不需要 mkBefore。
  environment.systemPackages = [pkgs.nix];

  # 注意：这里故意不碰 services.journald。
  # 上游就是因为写了 services.journald.settings，而它 pin 的 nixpkgs 根本没这个选项，
  # 导致整个 tarball 求值阶段直接失败。保持默认就好。

  # NixOS 要求显式声明，否则每次求值都打 warning。
  # 这个值与特性集绑定，不随发行版升级而变，改它需要同时读发布说明。
  system.stateVersion = lib.mkDefault "25.11";

  # ----------------------------------------------------------------
  # SSH：默认开启，监听 22 端口（容器内部端口，App 侧会做端口映射）
  # ----------------------------------------------------------------
  services.openssh = {
    enable = true;
    ports = [22];

    # 固定 host key，且首启即生成。
    #
    # 默认值（nixos-unstable）带 mldsa44-ed25519 这种后量子混合密钥，很多
    # 安卓端 SSH 客户端不认，握手会直接断。这里只留 RSA + ed25519，
    # 并显式列出而不是依赖默认值，避免上游改默认后又悄悄坏掉。
    hostKeys = [
      {
        path = "/etc/ssh/ssh_host_ed25519_key";
        type = "ed25519";
      }
      {
        path = "/etc/ssh/ssh_host_rsa_key";
        type = "rsa";
        bits = 4096;
      }
    ];
    # 镜像里 /etc/ssh 是空的，必须让 sshd-keygen 在开机时自己生成，
    # 否则 sshd 找不到 HostKey 会直接退出，表现就是「端口连不上」。
    generateHostKeys = true;

    # 认证走 PAM（见下方 UsePAM 说明），这样 passwd 改的密码能直接用于 SSH。
    settings = {
      PasswordAuthentication = true;
      PermitRootLogin = "yes";
      X11Forwarding = false;
      # 关掉 kbd-interactive：PAM 开启后它会和 password 认证重复提示，
      # 客户端上表现为连点两次密码框。
      KbdInteractiveAuthentication = false;

      # UsePAM = true（原来是 false）。
      #
      # 关闭 PAM 时 sshd 直接用 crypt(3) 校验 /etc/shadow，只认固定几种哈希。
      # 而 passwd 在新版 libxcrypt 下写的是 yescrypt（$y$），走不通这条路；
      # 表现就是「密码明明改对了却登录不了，日志只有 Failed password」。
      # 打开 PAM 后由 pam_unix 校验，yescrypt / SHA-512 都正常，
      # passwd 改的密码也能立刻用于 SSH。
      #
      # nixpkgs 会在 UsePAM = true 时自动生成 security.pam.services.sshd
      # （含 unixAuth），并把 pam 依赖带进闭包，这里不需要额外声明。
      UsePAM = true;

      # KexAlgorithms / Ciphers / Macs 在 nixpkgs 里被显式声明为
      # nullOr (list of string)，传字符串会报 not of type list of string。
      # 注意键名是 Macs，不是 MACs——写成 MACs 会落到未声明的 atom 类型上。
      # 这三项在 sshd_config 里由 NixOS 自己用逗号拼接。
      KexAlgorithms = [
        "curve25519-sha256"
        "curve25519-sha256@libssh.org"
        "ecdh-sha2-nistp256"
        "ecdh-sha2-nistp384"
        "ecdh-sha2-nistp521"
        "diffie-hellman-group-exchange-sha256"
        "diffie-hellman-group16-sha512"
        "diffie-hellman-group14-sha256"
      ];
      Ciphers = [
        "chacha20-poly1305@openssh.com"
        "aes256-gcm@openssh.com"
        "aes128-gcm@openssh.com"
        "aes256-ctr"
        "aes192-ctr"
        "aes128-ctr"
      ];
      Macs = [
        "hmac-sha2-256-etm@openssh.com"
        "hmac-sha2-512-etm@openssh.com"
        "umac-128-etm@openssh.com"
        "hmac-sha2-256"
        "hmac-sha2-512"
      ];
    };
  };

  # 容器里本来就关着防火墙，这里只是让选项语义明确。
  services.openssh.openFirewall = false;

  # ----------------------------------------------------------------
  # 内置普通用户：nixos
  # ----------------------------------------------------------------
  users.users.nixos = {
    isNormalUser = true;
    # home 手动指定，与上游模板保持一致，方便文档写绝对路径。
    home = "/home/nixos";
    createHome = true;
    # 密码以 SHA-512 crypt 形式固化。NixOS 默认就把哈希写进 /etc/shadow，
    # 不会出现明文密码落在 nix store 里的情况。
    # SHA-512 crypt of the shipped default password. Written on every
    # activation, so a `passwd` change is reverted on the next boot by design:
    # the image password is reproducible, not per-container state.
    hashedPassword = "$6$nixosrootfs$1kyaswk/G4wkgZzZOSYtIkFAFdtk1UeIpKNwH07LpCtpe8hg4OdfwIkq4C6o8qhr6rVf5gDxjmYCjMinScoXC0";
    # wheel 给 sudo 权限，其余是 Android 内核上真正能用的几个组：
    # aid_inet / aid_net_raw 才能建 socket、发原始包。
    extraGroups = ["wheel" "aid_inet" "aid_net_raw" "input" "video" "tty"];
    shell = pkgs.bash;
  };

  # 让 wheel 能 sudo，否则新用户拿不到 root。
  security.sudo.wheelNeedsPassword = true;
}
