import json
import pathlib

# ---------- 1) systems.json: aarch64 only by default ----------
p = pathlib.Path('systems.json')
systems = json.loads(p.read_text(encoding='utf-8'))
x86 = systems.pop('x86_64-linux')
# Keep x86 in the file but marked disabled, so re-enabling is one flag away.
systems['aarch64-linux']['enabled'] = True
x86['enabled'] = False
systems['x86_64-linux'] = x86
p.write_text(json.dumps(systems, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
print('systems.json:', json.dumps(systems, ensure_ascii=False))

# ---------- 2) plan_build.py: honour the enabled flag ----------
pb = pathlib.Path('scripts/plan_build.py')
s = pb.read_text(encoding='utf-8')

old = '''def load_systems(path: Path) -> dict:
    systems = load_json(path)
    if not isinstance(systems, dict) or not systems:
        fail(f"{path} must be a non-empty object")
    for system, meta in systems.items():
        for key in ("arch", "runner"):
            if not meta.get(key):
                fail(f"{path}['{system}'] is missing '{key}'")
    return systems'''

new = '''def load_systems(path: Path, include_disabled: bool = False) -> dict:
    """Load the system table.

    `enabled: false` marks a system as configured but not built by default, so
    the x86_64 entry can stay documented without running a runner for it on
    every build. `--include-disabled-systems` overrides that.
    """
    systems = load_json(path)
    if not isinstance(systems, dict) or not systems:
        fail(f"{path} must be a non-empty object")
    for system, meta in systems.items():
        for key in ("arch", "runner"):
            if not meta.get(key):
                fail(f"{path}['{system}'] is missing '{key}'")
    if include_disabled:
        return systems
    enabled = {k: v for k, v in systems.items() if v.get("enabled", True)}
    if not enabled:
        fail(f"{path} has no enabled systems")
    return enabled'''

assert old in s, 'load_systems anchor missing'
s = s.replace(old, new, 1)

# new CLI flag
s = s.replace(
    'parser.add_argument("--include-experimental", default="true", help="\'false\' to skip experimental variants")',
    'parser.add_argument("--include-experimental", default="true", help="\'false\' to skip experimental variants")\n'
    '    parser.add_argument("--include-disabled-systems", default="false", help="\'true\' to also build systems marked enabled: false")'
)

# pass the flag through to load_systems
s = s.replace(
    'all_systems = load(REPO_ROOT / "systems.json")',
    'all_systems = load_systems(\n        REPO_ROOT / "systems.json",\n        include_disabled=args.include_disabled_systems.strip().lower() == "true",\n    )'
)

pb.write_text(s, encoding='utf-8')
print('plan_build.py patched:', 'include_disabled_systems' in s)