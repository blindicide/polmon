# Orchestration lifecycle

Every execution backend implements `validate`, `create`, `start`, `stop`, `destroy`, and `inspect`.
The controller permits `new → validated → created → running → stopped → running` and terminal
destruction. Repeated validation, creation, start, stop, and destruction are idempotent in their
settled states. Destroying a running topology stops it first.

Created resources have globally unique ownership IDs. Claims are atomic; collisions cause cleanup
of the losing deployment. A partial create is destroyed and returns to `validated`. Other failed
operations retain the last consistent state. Destruction releases ownership in a `finally` path and
can be retried. Public errors identify the backend, operation, and exception type without leaking
local paths or arbitrary exception text.

