"""
Engine tests — run the same checks against Delta and Iceberg tables.
Zero-JVM: fixtures build tables with delta-rs / PyIceberg (see conftest).
"""

from lakecheck.engine import (
    check_duplicate_pks,
    check_null_spikes,
    check_row_count_drop,
    check_schema_drift,
)
from lakecheck.readers import get_reader

# ------------------------------------------------------------------- Delta


def test_delta_schema_drift(delta_schema_drift_table):
    reader = get_reader(delta_schema_drift_table, "delta")
    diff = check_schema_drift(reader, version_n=1)
    assert diff.has_drift() is True
    assert "age" in diff.added_columns
    assert "status" in diff.removed_columns


def test_delta_row_count_drop(delta_row_drop_table):
    reader = get_reader(delta_row_drop_table, "delta")
    diff = check_row_count_drop(reader, version_n=1, threshold_pct=-10.0)
    assert diff.version_n_added_rows == 2
    assert diff.version_n_minus_1_added_rows == 10
    assert diff.percentage_change == -80.0
    assert diff.exceeds_threshold is True


def test_delta_null_spikes(delta_null_dup_table):
    reader = get_reader(delta_null_dup_table, "delta")
    results = check_null_spikes(reader, version_n=1, columns=["email"])
    assert len(results) == 1
    assert results[0].spike_detected is True
    assert results[0].version_n_null_pct == 100.0


def test_delta_duplicate_pks(delta_null_dup_table):
    reader = get_reader(delta_null_dup_table, "delta")
    result = check_duplicate_pks(reader, version_n=1, pk_columns=["id"])
    assert result.has_duplicates is True
    assert result.duplicate_count == 1


def test_delta_autodetect(delta_row_drop_table):
    """No --format → detected as delta by the _delta_log/ layout."""
    reader = get_reader(delta_row_drop_table)
    assert reader.format.value == "delta"
    assert reader.latest_version() == 1


# ----------------------------------------------------------------- Iceberg


def test_iceberg_row_count_drop(iceberg_row_drop_table):
    reader = get_reader(iceberg_row_drop_table, "iceberg")
    diff = check_row_count_drop(reader, version_n=1, threshold_pct=-10.0)
    assert diff.version_n_added_rows == 2
    assert diff.version_n_minus_1_added_rows == 10
    assert diff.percentage_change == -80.0
    assert diff.exceeds_threshold is True


def test_iceberg_null_spikes(iceberg_null_dup_table):
    reader = get_reader(iceberg_null_dup_table, "iceberg")
    results = check_null_spikes(reader, version_n=1, columns=["email"])
    assert len(results) == 1
    assert results[0].spike_detected is True
    assert results[0].version_n_null_pct == 100.0


def test_iceberg_duplicate_pks(iceberg_null_dup_table):
    reader = get_reader(iceberg_null_dup_table, "iceberg")
    result = check_duplicate_pks(reader, version_n=1, pk_columns=["id"])
    assert result.has_duplicates is True
    assert result.duplicate_count == 1


def test_iceberg_autodetect(iceberg_row_drop_table):
    """No --format → detected as iceberg by metadata/*.metadata.json layout."""
    reader = get_reader(iceberg_row_drop_table)
    assert reader.format.value == "iceberg"
