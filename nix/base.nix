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

  # 允许 root 直登（容器里 root 就是默认用户）。
  services.openssh.enable = lib.mkDefault true;

  # 注意：这里故意不碰 services.journald。
  # 上游就是因为写了 services.journald.settings，而它 pin 的 nixpkgs 根本没这个选项，
  # 导致整个 tarball 求值阶段直接失败。保持默认就好。
}
