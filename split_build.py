import pathlib

p = pathlib.Path('.github/workflows/build-nixos-rootfs.yml')
s = p.read_text(encoding='utf-8')

start = s.index('  build:\n')
end = s.index('  release:\n')
build_block = s[start:end]

# Keep everything from the steps section onwards; replace only the head.
steps_idx = build_block.index('    steps:\n')
steps = build_block[steps_idx:]

new_head = '''  build:
    name: ${{ matrix.system }} / ${{ matrix.variant_id }}
    needs: plan
    # runs-on is a literal per job. It cannot be ${{ matrix.runner }} when the
    # matrix comes from needs.plan.outputs.matrix: GitHub resolves runs-on
    # while building the job graph, before any job output exists, and the run
    # dies with startup_failure before a single job is scheduled.
    #
    # aarch64 needs an ARM runner and x86_64 needs an x86 one, so the two
    # architectures live in separate jobs. The plan job still decides which
    # variants and whether each job runs at all.
    runs-on: ubuntu-24.04-arm
    timeout-minutes: 350
    # Skip entirely when the plan produced no aarch64 entries.
    if: ${{ needs.plan.outputs.has_aarch64 == 'true' }}
    strategy:
      fail-fast: false
      matrix:
        include: ${{ fromJSON(needs.plan.outputs.matrix_aarch64) }}
'''

new_build = new_head + steps.rstrip() + '\n\n'

x86_job = '''  build-x86:
    name: ${{ matrix.system }} / ${{ matrix.variant_id }}
    needs: plan
    # See the note on `build`: runs-on cannot depend on a runtime matrix.
    runs-on: ubuntu-latest
    timeout-minutes: 350
    # x86_64 is disabled by default in systems.json, so this job is usually
    # skipped rather than cancelled.
    if: ${{ needs.plan.outputs.has_x86_64 == 'true' }}
    strategy:
      fail-fast: false
      matrix:
        include: ${{ fromJSON(needs.plan.outputs.matrix_x86_64) }}
'''

# Reuse the same steps for the x86 job, but the store cache key differs only
# by the system value inside the matrix, so no edit is needed.
s = s[:start] + new_build + x86_job + steps + s[end:]

p.write_text(s, encoding='utf-8')
print('build split into build + build-x86')
print('has build-x86:', '  build-x86:' in s)