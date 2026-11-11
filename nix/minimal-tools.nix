{ pkgs, ... }: {
  # 最小镜像的包 + 日常运维工具。
  environment.systemPackages = [
    pkgs.bash
    pkgs.coreutils
    pkgs.findutils
    pkgs.gnugrep
    pkgs.gnused
    pkgs.gawk
    pkgs.tar
    pkgs.gzip
    pkgs.xz
    pkgs.less
    pkgs.nano
    # 以下为 minimal-tools 额外带上的
    pkgs.git
    pkgs.curl
    pkgs.wget
    pkgs.procps
    pkgs.iproute2
    pkgs.iputils
    pkgs.which
    pkgs.openssh
    pkgs.cacert
  ];
}
