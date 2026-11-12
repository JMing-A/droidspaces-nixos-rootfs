import pathlib

p = pathlib.Path('scripts/plan_build.py')
s = p.read_text(encoding='utf-8')

old = '''    lines = {
        "tag": tag,
        "build_date": build_date,
        "flake_base": base,
        "flake_ref": flake_ref,
        "matrix": json.dumps(matrix, separators=(",", ":")),
        "job_count": str(len(matrix["include"])),
        "variant_count": str(len(variants)),
        "system_count": str(len(systems)),
        "experimental_count": str(sum(1 for v in variants if v.get("experimental"))),
    }'''

new = '''    # The workflow cannot use one matrix for runs-on: GitHub resolves runs-on
    # while building the job graph, before any job output exists, so a matrix
    # derived from needs.<job>.outputs makes the whole run fail at startup.
    # Instead the entries are split per runner and each job gets a literal
    # runs-on plus a has_<arch> flag it can gate on with `if`.
    by_runner: dict[str, list[dict]] = {}
    for entry in matrix["include"]:
        by_runner.setdefault(entry["runner"], []).append(entry)

    lines = {
        "tag": tag,
        "build_date": build_date,
        "flake_base": base,
        "flake_ref": flake_ref,
        "matrix": json.dumps(matrix, separators=(",", ":")),
        "job_count": str(len(matrix["include"])),
        "variant_count": str(len(variants)),
        "system_count": str(len(systems)),
        "experimental_count": str(sum(1 for v in variants if v.get("experimental"))),
    }

    for runner, entries in by_runner.items():
        # runner labels contain dots and dashes, which are not valid in an
        # output name; normalise to underscore form.
        key = runner.replace(".", "_").replace("-", "_")
        lines[f"matrix_{key}"] = json.dumps({"include": entries}, separators=(",", ":"))

    # Explicit flags so the job-level `if` never evaluates to an empty string.
    systems_enabled = {entry["system"] for entry in matrix["include"]}
    lines["has_aarch64"] = "true" if "aarch64-linux" in systems_enabled else "false"
    lines["has_x86_64"] = "true" if "x86_64-linux" in systems_enabled else "false"'''

assert old in s, 'outputs block not found'
s = s.replace(old, new, 1)
p.write_text(s, encoding='utf-8')
print('plan_build.py outputs extended')