# Resource budget

The engineering budget is two CPU cores and 2 GB physical RAM. Normal tests use small topologies;
100- and 250-endpoint benchmarks require explicit invocation. The initial target is 50 L0 plus two
L1 endpoints within about 1 GB incremental RSS, subject to measurement. Admission control must
reject unsafe workloads before the OOM killer becomes relevant. Swap is recorded but is never
counted as usable budget.

Measurements supporting or refuting the target are produced by `polmon-benchmark target` (50 L0 +
2 L1 service endpoints) and retained with their host description in `benchmarks/results/`. Memory
attributable to processes (control process plus L1 service process trees) is reported separately
from the host `MemAvailable` delta, which also includes unattributable kernel objects and unrelated
host activity. See [docs/BENCHMARKS.md](docs/BENCHMARKS.md).
