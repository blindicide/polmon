# Detailed logs

The backend keeps a bounded, structured view of lab activity separate from the experiment
telemetry event stream. Each JSON-line record contains:

```json
{"cursor": 42, "timestamp": "2026-09-28T12:00:00+00:00", "level": "INFO",
 "logger": "polmon.lab", "event": "lab.service.start", "message": "Service started",
 "params": {"service": "sshd"}, "correlation": {"topology": "log-lab",
 "node": {"id": "bravo", "name": "Bravo", "uuid": "..."}}}
```

The in-process ring retains the most recent 5,000 records. The backend also writes
`<data-directory>/logs/polmon.jsonl` and rotates up to four numbered files when a file reaches
256 KiB. Service output is captured in bounded files below `logs/services/`, and console-session
output is below `logs/console/`; the files endpoint reports their paths and sizes. Record fields,
parameters, excerpts and file sizes are bounded. Credential-like parameter names are redacted.

Lab lifecycle, interface, service, console, experiment-action and teardown events carry the
relevant deployment, topology, experiment, session and node (id/name/UUID) correlations. Use a
node UUID as the most stable cross-operation filter.

## API

- `GET /v1/logs` returns bounded records. Filters are `level`, `source`, `deployment`, `topology`,
  `node` (id, name or UUID substring), `session`, `experiment`, `search`, `since` (cursor), and
  `limit` (1–500). The response has `records`, `next_cursor` and `has_more`.
- `GET /v1/logs/stream?since=N&limit=N` provides a bounded Server-Sent Events follow stream.
  Each `log` event has the record cursor as its SSE `id`; heartbeat comments keep the connection
  active. Clients should reconnect with the last cursor.
- `GET /v1/logs/files` lists the log directory, bounded file size and current file sizes. It never
  returns file contents.
- `polmon-diagnostics --logs --json --data-directory DIR` reports the same file index and the last
  bounded error records. Without `--logs`, diagnostics remains side-effect free.

Errors returned by the API contain safe error documents; detailed log content is not copied into
error messages or error payloads. The desktop Logs page provides level/source/deployment/node/text
filters, follow polling, row JSON detail, file metadata, clipboard copy and bounded JSON export.

## Reading a bundle

Start with the UUID or deployment cursor from the operation under investigation, query `/v1/logs`
with `node=<uuid>` or `deployment=<id>`, then inspect the `params` and `correlation` objects in
cursor order. Check `/v1/logs/files` for service output when an event proves that a process was
started but its behavior needs detail. Files are intentionally capped; older records and output
may have rotated out.
