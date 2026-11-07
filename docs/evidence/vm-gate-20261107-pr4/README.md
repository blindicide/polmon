# PR #4 local real-KVM lifecycle evidence — 2026-11-07

Source commit: `4a3f5fe` (clean tracked working tree; includes fixes in `8a10799`).
The later commit adding this evidence does not change runtime code.

Command from the repository root:

```sh
.venv/bin/python scripts/vm-gate.py --mode both \
  --image /tmp/opencode/polmon-pr4-alpine.qcow2 \
  --manifest examples/vm/alpine-3.24.1-manifest.json \
  --output /tmp/opencode/polmon-pr4-vm-gate-final
```

The base was copied from the existing local image, made read-only, and verified
against SHA-256 `6e2e6fe0572b6632527f268d3659e8fccebda4e1ee470fafe2c4d7b85b6a4df6`.
No image download or modification of the original image was needed. Host CPU,
QEMU, platform, source identity and measurements are recorded in `summary.json`.

Each mode boots two independent 256 MiB/one-vCPU Alpine guests. The raw pytest
logs and JUnit retain the actual result, and the summary retains per-guest
process, interface and allocated-overlay measurements. The test checks exact
identity and wrong-identity rejection, guest-to-guest HTTP, host/egress isolation,
guest-written overlay differences, unchanged base digest and cleanup. The netns
harness also compares host network/firewall state and checks for leaked lab
resources/processes.

These are laptop lifecycle observations, not published-release validation,
native Windows results, a controlled performance benchmark, full real-guest
failure/recovery acceptance or a security certification. Other GUI validation
ran concurrently; do not generalize the samples into resource-budget claims.
`integration_verified` remains false and the addon remains experimental.

The older failing hosted checks at `1a99d08` remain available:
[CI](https://github.com/blindicide/polmon/actions/runs/40130947922),
[VM gate](https://github.com/blindicide/polmon/actions/runs/40130948058).
Neither was bypassed or waived.
