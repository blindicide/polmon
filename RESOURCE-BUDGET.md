# Resource budget

The engineering budget is two CPU cores and 2 GB physical RAM. Normal tests use small topologies;
100- and 250-endpoint benchmarks require explicit invocation. The initial target is 50 L0 plus two
L1 endpoints within about 1 GB incremental RSS, subject to measurement. Admission control must
reject unsafe workloads before the OOM killer becomes relevant. Swap is recorded but is never
counted as usable budget.

