# Droidspaces NixOS rootfs builder

Builds NixOS rootfs tarballs for [Droidspaces](https://github.com/ravindu644/Droidspaces-OSS), publishes
them as GitHub releases, and keeps `rootfs.json` in sync with the published assets.

The rootfs definitions live in the upstream flake, not here: this repository is only the
build and release pipeline. Nothing is built from Dockerfiles, and nothing is vendored — every
run points at a flake ref you choose.

## Why NixOS is built here instead of in the main template pipeline

Upstream added a NixOS job to its Dockerfile pipeline in May 2026 and removed it again in
September 2026 when that pipeline was refactored to be label-driven. A NixOS image cannot be
expressed as a `droidspaces.*` label on a Dockerfile, so the build moved out rather than disappeared.
This repository is that pipeline, rebuilt as a standalone, manually triggered workflow.

## Layout

```
variants.json                     what to build: id, name, distro, description, flake attr
systems.json                      system -> arch + CI runner
scripts/plan_build.py             workflow_dispatch inputs -> build matrix
scripts/gen_rootfs_json.py        release assets -> rootfs.json (with --lint)
scripts/write_notes.py            rootfs.json -> release notes
.github/workflows/build-nixos-rootfs.yml   manual build + release
rootfs.json                       generated, do not edit by hand
```

## Running a build

Actions → **Build NixOS rootfs** → *Run workflow*. Nothing runs on push, on a schedule, or on
pull requests; every build is a deliberate click.

| input | default | meaning |
|---|---|---|
| `variants` | `all` | `all`, or comma separated ids from `variants.json` |
| `systems` | `all` | `all`, or comma separated systems from `systems.json` |
| `include_experimental` | `true` | `false` drops variants flagged `experimental` |
| `publish` | `true` | `false` builds and uploads artifacts only, no release, no commit |
| `tag` | empty | release tag; empty means `v<UTC now>` |
| `flake_repo` | `github:ravindu644/Droidspaces-OSS` | flake holding the rootfs definitions |
| `flake_ref` | `main` | ref inside that repo |

A single-variant smoke test:

```
variants = minimal
systems  = aarch64-linux
publish  = false
```

## Variants

| id | flake attribute | notes |
|---|---|---|
| `minimal` | `nixosDroidspacesTarballs.<system>.minimal` | systemd version comes from the pinned nixpkgs |
| `minimal-v257` | `...minimal-with-systemd-v257` | separate nixpkgs input carrying systemd v257 |
| `minimal-pinned-v257` | `...minimal-with-pinned-systemd-v257` | default nixpkgs, systemd overridden to v257 |
| `minimal-v259` | `...minimal-with-systemd-v259` | **experimental** — upstream dropped it after it failed to build |
| `finix-experimental` | `finixDroidspacesTarballs.<system>.experimental` | **experimental** — finix community modules |

Add a variant by appending to `variants.json`; the matrix, `rootfs.json` and the release notes
all derive from it. `python3 scripts/gen_rootfs_json.py --lint` validates the table without
building anything.

## How the pipeline works

1. **plan** lints `variants.json` / `systems.json`, resolves the tag, and emits the matrix as a
   workflow output.
2. **build** fans out one job per `(system, variant)` on the runner named in `systems.json`,
   installs Determinate Nix, restores `/nix` from the Actions cache, runs `nix build` on the
   flake attribute, renames the tarball to
   `<file>-Droidspaces-rootfs-<arch>-<build_date>-<tag>.tar.xz`, and uploads it as an artifact.
3. **release** downloads every artifact, regenerates `rootfs.json` with fresh SHA256 and sizes,
   creates the release, then commits the updated `rootfs.json` back to the default branch.

A partial run is allowed: if you build only some variants, `rootfs.json` is regenerated with
`--allow-partial` and only lists what this release actually contains.

`fail-fast` is off, so one broken variant does not hide the state of the others. The release job
still requires every build job to succeed, so a failed variant blocks publishing — rerun the
workflow with a narrower `variants` value if you need to ship the healthy ones.

## Known upstream breakage

`github:ravindu644/Droidspaces-OSS` at `main` does **not** evaluate as of this writing. Commit
`bf2aa0b` (2026-09-12) moved journald config to `services.journald.settings.Journal`, an option
that does not exist in the pinned nixpkgs `c6e5ca3`, so every variant dies with:

```
error: The option `services.journald.settings' does not exist.
```

Until that is fixed upstream, pin `flake_ref` to a tag that still uses `services.journald.extraConfig`:

| ref | `services.journald` option used | usable |
|---|---|---|
| `v6.5.5` | `extraConfig` | yes |
| `v6.6.0` and later, including `main` | `settings.Journal` | **no**, evaluation error |

So the working invocation today is `flake_ref = v6.5.5`. Revert to `main` once upstream repairs the
option. This is a defect in the flake, not in this pipeline: the pipeline reaches the evaluation
stage, resolves the flake, and fails inside `config.system.build.tarball`.

## Building locally

```sh
nix build github:ravindu644/Droidspaces-OSS#legacyPackages.aarch64-linux.nixosDroidspacesTarballs.aarch64-linux.minimal
```

Then feed the tarballs into the index generator:

```sh
python3 scripts/gen_rootfs_json.py \
  --dist dist --out rootfs.json --repo <owner>/<repo> \
  --version v20261111-185500 --allow-partial
```

## Licence

The pipeline in this repository is GPL-3.0, matching
[Droidspaces-OSS](https://github.com/ravindu644/Droidspaces-OSS). The rootfs images it builds
contain their own software with their own licences.
