# Expanded hosted KVM gate — PASS

Source PR head: `baae2495accac5f7d61e588e633df8fe920612be`.
GitHub run: https://github.com/blindicide/polmon/actions/runs/42349649597
Artifact: `vm-gate-evidence`, downloaded unchanged after successful completion.

GitHub's pull-request checkout tested synthetic merge commit
`2b1759c22f4e5270a541a9475559f2ef108cc60f`, with parents
`5aa4c96fb555098acba4f56a5111875d502b2b1c` and the source PR head above.
The artifact reports `git_dirty: false`. This synthetic test merge is **not** a
merge of PR #4, which remains draft and unmerged.

Both userns and netns passed **11 tests each**, with zero failures, errors or skips:

- Two-guest lifecycle, exact identities, guest HTTP, isolation, measurements,
  guest-written overlays, unchanged pinned base and teardown.
- Seven faults: guest crash, readiness timeout, partial startup, API cancel/timeout,
  VM-command SIGKILL, and backend death followed by successor recovery.
- Mixed guest/L0/namespace communication and isolation, partial namespace rollback,
  and nested-owner recovery before guest startup.

The netns run's outer guard also reports unchanged host networking and no remaining
platform lab resources or processes. Summary, raw pytest logs and JUnit are retained
beside this note. Measurements describe this hosted runner, not a general cost guarantee.

All five native CI checks at the same PR head passed too:
https://github.com/blindicide/polmon/actions/runs/42349649584

This successful expanded run supersedes the local rerun blocker, but does not erase
its failed result (retained separately under `vm-followup-20261107-pr4`). No check was
waived. Specific passing tests are not comprehensive security acceptance;
`integration_verified` stays false. No release, tag, merge or waiver was created.
