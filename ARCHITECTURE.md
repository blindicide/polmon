# Architecture

The control plane is a Python 3.12 package. FastAPI exposes backend services while the Tkinter
client communicates only through documented HTTP contracts. Execution backends sit behind an
orchestration interface: shared-process L0 endpoints, Linux namespace L1 endpoints, and a future
KVM-compatible L2 adapter. SQLite stores bounded experiment metadata; YAML is the declarative
input format.

Dependencies point inward: GUI and API depend on control-plane models, while synthetic and Linux
networking implementations never depend on the GUI. This keeps Windows packaging independent of
Linux facilities and permits unit testing without privileges.

