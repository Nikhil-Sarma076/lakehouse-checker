# Testing Guide — lakecheck

How to verify `lakecheck` works, from unit tests through linting to end-to-end
CLI smoke tests. **Everything runs zero-JVM** — no Java, no Spark.

## Testing philosophy

Three layers, mirroring CI:

| Layer              | Command                    | Validates                                                        |
| ------------------ | -------------------------- | ---------------------------------------------------------------- |
| **Lint + Format**  | `ruff format --check .`    | Style (line length 100, isort)                                   |
|                    | `ruff check .`             | Static analysis + security (`flake8-bandit` / S)                 |
| **Unit Tests**     | `pytest -v tests/`         | Every check for **both Delta and Iceberg**, storage, reporters, CLI |
| **E2E Smoke Test** | `python3 scripts/smoke_test.py` | Real Delta + Iceberg tables through the full CLI → reporter → exit code |

## Prerequisites

- **Python** ≥ 3.9
- **No Java / no Spark.** Delta metadata is read via delta-rs (`deltalake`),
  Iceberg via PyIceberg, and O(Δ) data scans via PyArrow — all pure Python/native.
- Install dev dependencies:

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
```

## Running the tests

```bash
pytest -v tests/            # 20 tests — Delta + Iceberg engine, storage, reporters, CLI
ruff format --check .       # style
ruff check .                # lint + security
python3 scripts/smoke_test.py   # E2E: builds real Delta + Iceberg tables, runs the CLI
```

## What the fixtures build (zero-JVM)

`tests/conftest.py` creates tables with the same libraries the tool uses:

- **Delta** fixtures via `deltalake.write_deltalake` (schema-drift, null+duplicate,
  row-count-drop tables).
- **Iceberg** fixtures via a local SQLite `SqlCatalog` over a `file://` warehouse
  (`tbl.append(...)` per snapshot). No catalog service, no MinIO.

Each fixture yields a table *path* so the same assertions run against either
format through `get_reader(path, fmt)`.

## The performance contract under test

- **O(1)** — schema drift, row-count drop: read only transaction-log / metadata
  JSON. Tests assert exact added-row counts and drift without any data scan.
- **O(Δ)** — null spikes, duplicate PKs: read only the data files *added* by the
  target commit, into PyArrow. Tests assert 100% null and 1 duplicate on the
  new-commit files only.

## Troubleshooting

| Symptom                                   | Fix                                                            |
| ----------------------------------------- | ------------------------------------------------------------- |
| `No _delta_log found` / `No *.metadata.json` | Point at a real table root, or pass `--format` explicitly.    |
| Iceberg test import errors                | Ensure `pyiceberg[pyarrow]` installed (in `[dev]`).           |
| S3 tables not read                        | Set `AWS_ENDPOINT_URL` / `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_REGION`. |
