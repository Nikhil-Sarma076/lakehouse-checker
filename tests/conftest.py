"""
Pytest fixtures — zero-JVM.
==========================
Delta tables are built with delta-rs (``deltalake``) and Iceberg tables with
PyIceberg (local SQLite catalog + file warehouse). No Spark, no JRE — the same
zero-JVM stack the checker itself uses.

Each fixture yields a table *path* so the same test body can run against either
format via ``get_reader(path, fmt)``.
"""

import os
import tempfile
from typing import Generator

import pyarrow as pa
import pytest

# --------------------------------------------------------------------------- Delta


def _write_delta(path, table, mode="error"):
    from deltalake import write_deltalake

    write_deltalake(path, table, mode=mode)


@pytest.fixture
def delta_schema_drift_table() -> Generator[str, None, None]:
    """v0: {id, status}; v1 overwrites with {id, age} → add 'age', remove 'status'."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "schema_drift")
        _write_delta(path, pa.table({"id": [1], "status": ["active"]}))
        from deltalake import write_deltalake

        write_deltalake(
            path, pa.table({"id": [1], "age": [25]}), mode="overwrite", schema_mode="overwrite"
        )
        yield path


@pytest.fixture
def delta_null_dup_table() -> Generator[str, None, None]:
    """v0: one clean row; v1 appends two rows with null email and duplicate id=2."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "null_dup")
        _write_delta(path, pa.table({"id": [1], "email": ["alice@test.com"]}))
        _write_delta(
            path,
            pa.table({"id": [2, 2], "email": pa.array([None, None], type=pa.string())}),
            mode="append",
        )
        yield path


@pytest.fixture
def delta_row_drop_table() -> Generator[str, None, None]:
    """v0: 10 rows; v1 appends 2 → 80% drop in added rows."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "row_drop")
        _write_delta(path, pa.table({"id": list(range(10))}))
        _write_delta(path, pa.table({"id": [10, 11]}), mode="append")
        yield path


# ------------------------------------------------------------------------- Iceberg


@pytest.fixture
def iceberg_catalog(tmp_path_factory):
    """Local SQLite-backed Iceberg catalog over a file:// warehouse (no catalog svc)."""
    from pyiceberg.catalog.sql import SqlCatalog

    base = tmp_path_factory.mktemp("iceberg_wh")
    catalog = SqlCatalog(
        "test",
        uri=f"sqlite:///{base}/catalog.db",
        warehouse=f"file://{base}",
    )
    catalog.create_namespace("default")
    return catalog


def _iceberg_table_path(catalog, identifier):
    return catalog.load_table(identifier).location()


@pytest.fixture
def iceberg_null_dup_table(iceberg_catalog) -> str:
    """v0(snapshot0): clean row; v1(snapshot1): append null email + duplicate id=2."""
    t0 = pa.table({"id": pa.array([1], pa.int64()), "email": ["alice@test.com"]})
    tbl = iceberg_catalog.create_table("default.null_dup", schema=t0.schema)
    tbl.append(t0)
    tbl.append(
        pa.table({"id": pa.array([2, 2], pa.int64()), "email": pa.array([None, None], pa.string())})
    )
    return _iceberg_table_path(iceberg_catalog, "default.null_dup")


@pytest.fixture
def iceberg_row_drop_table(iceberg_catalog) -> str:
    """snapshot0: 10 rows; snapshot1: 2 rows → 80% drop."""
    t0 = pa.table({"id": pa.array(list(range(10)), pa.int64())})
    tbl = iceberg_catalog.create_table("default.row_drop", schema=t0.schema)
    tbl.append(t0)
    tbl.append(pa.table({"id": pa.array([10, 11], pa.int64())}))
    return _iceberg_table_path(iceberg_catalog, "default.row_drop")
