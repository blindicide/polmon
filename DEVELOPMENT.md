# Development

Use only Python 3.12 through the project environment:

```bash
uv venv --python /usr/bin/python3.12
uv pip install -e '.[dev,build]'
.venv/bin/ruff check .
.venv/bin/pytest -m 'not privileged and not performance'
```

Keep unit, integration, privileged, performance, and smoke tests explicitly marked. Default tests
must fit two CPU cores and 2 GB RAM. Add dependencies only with a documented purpose and resource
cost. Source, documentation, generated reports, and logs use UTF-8.

