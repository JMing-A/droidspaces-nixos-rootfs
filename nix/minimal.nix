# 最小变体：只要能开机、能登录、能装包。
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
  ];
}
