# 最小变体 + 日常运维工具，体积会比 minimal 大几十 MB。
{ pkgs, ... }: {
  environment.systemPackages = with pkgs; [
    bash
    coreutils
    findutils
    gnugrep
    gnused
    gawk
    tar
    gzip
    xz
    less
    nano
    # 以下为 minimal-tools 额外带上的
    git
    curl
    wget
    procps
    iproute2
    iputils
    which
    openssh
    cacert
  ];
}
