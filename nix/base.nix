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

  # 关掉 nix 自更新与 channel，镜像里用不到，还会在启动时挂 unit。
  nix.channel.enable = lib.mkDefault false;
  nix.settings.experimental-features = ["nix-command" "flakes"];

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
    # 容器里没有 PAM，也不接 ldap/sss，用原生 shadow 密码校验就行。
    settings = {
      PasswordAuthentication = true;
      PermitRootLogin = "yes";
      # 没有 PAM 时不走 kbd-interactive，避免登录挂住。
      KbdInteractiveAuthentication = false;
      UsePAM = false;
      X11Forwarding = false;
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
    hashedPassword = "$6$nixosrootfs$BEVYiYJfGKGS2sV3x4iae7Wj9dWkgw.JSGwmJSG2ugZB2I7LHn4nh3/TOeVEQWlyHF0nJIyyxqB2i7xwUzltr1";
    # wheel 给 sudo 权限，其余是 Android 内核上真正能用的几个组：
    # aid_inet / aid_net_raw 才能建 socket、发原始包。
    extraGroups = ["wheel" "aid_inet" "aid_net_raw" "input" "video" "tty"];
    shell = pkgs.bash;
  };

  # 让 wheel 能 sudo，否则新用户拿不到 root。
  security.sudo.wheelNeedsPassword = true;
}
