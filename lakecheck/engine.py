"""
Check Engine (format-agnostic, zero-JVM)
========================================
The four data-quality checks, expressed against the ``MetadataReader`` protocol
so they work identically for Delta and Iceberg. No Spark: O(1) checks read only
metadata; O(Δ) checks scan only the data files added by the target commit, in
PyArrow.

Performance contract:
- **O(1)** — schema drift, row-count drop: metadata/transaction-log only.
- **O(Δ)** — null spikes, duplicate PKs: PyArrow over the newly-added files.
"""

from typing import List, Optional

import pyarrow as pa
import pyarrow.compute as pc

from lakecheck.models import DuplicatePKResult, NullSpikeResult, RowCountDiff, SchemaDiff
from lakecheck.readers import MetadataReader


def check_schema_drift(reader: MetadataReader, version_n: int) -> SchemaDiff:
    """O(1): compare the active schema at version N vs N-1 from metadata only."""
    fields_n = reader.schema_at(version_n)
    fields_prev = reader.schema_at(version_n - 1)

    diff = SchemaDiff()
    for col, dtype in fields_n.items():
        if col not in fields_prev:
            diff.added_columns.append(col)
        elif fields_prev[col] != dtype:
            diff.type_changes[col] = f"{fields_prev[col]} -> {dtype}"
    for col in fields_prev:
        if col not in fields_n:
            diff.removed_columns.append(col)
    return diff


def check_row_count_drop(
    reader: MetadataReader, version_n: int, threshold_pct: float = -10.0
) -> RowCountDiff:
    """O(1): compare rows added by commit N vs N-1 from metadata stats."""
    rows_n = reader.added_rows_at(version_n)
    rows_prev = reader.added_rows_at(version_n - 1)

    if rows_prev == 0:
        pct_change = 0.0 if rows_n == 0 else 100.0
    else:
        pct_change = ((rows_n - rows_prev) / rows_prev) * 100.0

    return RowCountDiff(
        version_n_added_rows=rows_n,
        version_n_minus_1_added_rows=rows_prev,
        percentage_change=pct_change,
        exceeds_threshold=pct_change <= threshold_pct,
    )


def _null_pct(table: Optional[pa.Table], columns: List[str]) -> dict:
    """Null percentage per column via PyArrow compute (single pass, no Spark)."""
    if table is None or table.num_rows == 0:
        return {c: 0.0 for c in columns}
    total = table.num_rows
    out = {}
    for col in columns:
        if col in table.column_names:
            null_count = table.column(col).null_count
            out[col] = (null_count / total) * 100.0
        else:
            out[col] = 0.0
    return out


def check_null_spikes(
    reader: MetadataReader, version_n: int, columns: List[str]
) -> List[NullSpikeResult]:
    """O(Δ): null% in newly-added files of N vs N-1 (PyArrow, no Spark)."""
    paths_n = reader.added_data_files_at(version_n)
    paths_prev = reader.added_data_files_at(version_n - 1)

    table_n = reader.read_data_files(paths_n) if paths_n else None
    table_prev = reader.read_data_files(paths_prev) if paths_prev else None

    stats_n = _null_pct(table_n, columns)
    stats_prev = _null_pct(table_prev, columns)

    results = []
    for col in columns:
        pct_n = stats_n[col]
        pct_prev = stats_prev[col]
        results.append(
            NullSpikeResult(
                column=col,
                version_n_null_pct=pct_n,
                version_n_minus_1_null_pct=pct_prev,
                spike_detected=(pct_n - pct_prev) > 10.0,
            )
        )
    return results


def check_duplicate_pks(
    reader: MetadataReader, version_n: int, pk_columns: List[str]
) -> DuplicatePKResult:
    """O(Δ): duplicate PK groups within the newly-added files (PyArrow group_by)."""
    paths_n = reader.added_data_files_at(version_n)
    table_n = reader.read_data_files(paths_n) if paths_n else None

    if table_n is None or table_n.num_rows == 0:
        return DuplicatePKResult(has_duplicates=False, duplicate_count=0)

    missing = [c for c in pk_columns if c not in table_n.column_names]
    if missing:
        raise ValueError(f"PK column(s) not found in data: {missing}")

    # Group by the PK column(s), count rows per group, count groups with > 1 row.
    grouped = table_n.group_by(pk_columns).aggregate([(pk_columns[0], "count")])
    count_col = grouped.column(f"{pk_columns[0]}_count")
    duplicate_count = pc.sum(pc.greater(count_col, 1).cast(pa.int64())).as_py() or 0

    return DuplicatePKResult(
        has_duplicates=duplicate_count > 0,
        duplicate_count=int(duplicate_count),
    )
