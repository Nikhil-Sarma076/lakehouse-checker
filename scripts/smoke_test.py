"""End-to-end smoke test for lakecheck (zero-JVM).

Builds real multi-version Delta (delta-rs) and Iceberg (PyIceberg) tables, then
invokes the lakecheck CLI as a subprocess to verify the full pipeline
(CLI -> reader -> engine -> reporter -> exit code) for both formats. No Spark.

    python3 scripts/smoke_test.py
"""

import json
import os
import subprocess
import sys
import tempfile

import pyarrow as pa


def _run_cli(table, *extra):
    return subprocess.run(  # noqa: S603 - local dev smoke test, absolute interpreter path
        [sys.executable, "-m", "lakecheck.cli", table, "--json", *extra],
        capture_output=True,
        text=True,
    )


def _delta_clean(tmp):
    from deltalake import write_deltalake

    p = os.path.join(tmp, "delta_clean")
    write_deltalake(p, pa.table({"id": pa.array(list(range(10)), pa.int64())}))
    write_deltalake(p, pa.table({"id": pa.array(list(range(10, 20)), pa.int64())}), mode="append")
    return p


def _delta_anomaly(tmp):
    from deltalake import write_deltalake

    p = os.path.join(tmp, "delta_anomaly")
    write_deltalake(p, pa.table({"id": pa.array(list(range(10)), pa.int64())}))
    write_deltalake(p, pa.table({"id": pa.array([10, 11], pa.int64())}), mode="append")
    return p


def _iceberg_anomaly(tmp):
    from pyiceberg.catalog.sql import SqlCatalog

    cat = SqlCatalog("smoke", uri=f"sqlite:///{tmp}/c.db", warehouse=f"file://{tmp}")
    cat.create_namespace("default")
    t0 = pa.table({"id": pa.array(list(range(10)), pa.int64())})
    tbl = cat.create_table("default.ice_anomaly", schema=t0.schema)
    tbl.append(t0)
    tbl.append(pa.table({"id": pa.array([10, 11], pa.int64())}))
    return tbl.location()


def main():
    with tempfile.TemporaryDirectory() as tmp:
        print("=== SMOKE 1: Delta clean table (expect exit 0) ===")
        proc = _run_cli(_delta_clean(tmp))
        print("Exit:", proc.returncode)
        assert proc.returncode == 0, proc.stderr
        payload = json.loads(proc.stdout)
        assert payload["format"] == "delta" and payload["has_anomalies"] is False
        print("PASSED\n")

        print("=== SMOKE 2: Delta row-count-drop anomaly (expect exit 1) ===")
        proc = _run_cli(_delta_anomaly(tmp))
        print("Exit:", proc.returncode)
        assert proc.returncode == 1, proc.stderr
        payload = json.loads(proc.stdout)
        assert payload["row_count_diff"]["percentage_change"] == -80.0
        print("PASSED\n")

        print("=== SMOKE 3: Iceberg row-count-drop anomaly (expect exit 1) ===")
        proc = _run_cli(_iceberg_anomaly(tmp), "--format", "iceberg")
        print("Exit:", proc.returncode)
        assert proc.returncode == 1, proc.stderr
        payload = json.loads(proc.stdout)
        assert payload["format"] == "iceberg"
        assert payload["row_count_diff"]["percentage_change"] == -80.0
        print("PASSED\n")

    print("ALL SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
