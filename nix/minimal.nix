{ pkgs, ... }: {
  # 显式写 pkgs. 前缀：`with pkgs; [ tar ... ]` 中间有一层列表字面量，
  # 作用域提升不到列表元素上，会报 undefined variable。
  environment.systemPackages = [
    pkgs.bash
    pkgs.coreutils
    pkgs.findutils
    pkgs.gnugrep
    pkgs.gnused
    pkgs.gawk
    pkgs.gnutar
    pkgs.gzip
    pkgs.xz
    pkgs.less
    pkgs.nano
  ];
}
