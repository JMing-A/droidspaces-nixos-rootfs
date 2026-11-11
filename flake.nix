{
  description = "Droidspaces 用的 NixOS rootfs 压缩包构建";

  inputs = {
    # 单一输入：需要的所有 nixpkgs 模块都从这里来，不再额外 pin 别的 channel，
    # 避免出现「模块来自 A、选项来自 B」那种求值直接暴炸的局面。
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs = {
    self,
    nixpkgs,
  }: let
    inherit (nixpkgs) lib;

    # 与 systems.json 保持一致；CI 里的 runner 也按这两个 system 分配。
    systems = ["aarch64-linux" "x86_64-linux"];

    # 每个变体 = 一份额外的模块文件，叠在 base.nix 上面。
    # 新增变体：在 nix/ 下放一个模块，在这里加一行，再在 variants.json 里加一条。
    profiles = {
      minimal = ./nix/minimal.nix;
      minimal-tools = ./nix/minimal-tools.nix;
    };

    mkTarball = system: profile:
      (lib.nixosSystem {
        inherit system;
        modules = [
          ./nix/base.nix
          profiles.${profile}
        ];
      }).config.system.build.tarball;
  in {
    legacyPackages = lib.genAttrs systems (system: {
      nixosRootfsTarballs = lib.genAttrs (builtins.attrNames profiles) (profile: mkTarball system profile);
    });

    # 方便本地 `nix flake show` 看结构。
    formatter = lib.genAttrs systems (system: nixpkgs.legacyPackages.${system}.alejandra);
  };
}
