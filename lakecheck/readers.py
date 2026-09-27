"""
Metadata Readers (format abstraction)
=====================================
lakecheck runs the same four data-quality checks against either a Delta Lake or
an Apache Iceberg table. The only thing that differs per format is *how* we read
metadata and locate the data files added by a commit/snapshot. That difference
lives behind the ``MetadataReader`` protocol here; the engine and CLI never
branch on format.

Both readers preserve the performance contract:
- **O(1)** schema + row-count: read only transaction-log / metadata JSON, no scan.
- **O(Δ)** null / duplicate: read only the data files *added* by the target
  commit, into PyArrow — never a full-table scan, and never a JVM/Spark.
"""
import os
import json
from enum import Enum
from typing import Any, Dict, List, Protocol, runtime_checkable

import pyarrow as pa

from lakecheck import storage


class LakehouseFormat(str, Enum):
    DELTA = "delta"
    ICEBERG = "iceberg"


@runtime_checkable
class MetadataReader(Protocol):
    """What the checks need from a table, regardless of format."""

    format: LakehouseFormat

    def latest_version(self) -> int:
        """Highest commit version (Delta) / snapshot ordinal (Iceberg)."""
        ...

    def schema_at(self, version: int) -> Dict[str, str]:
        """Active schema at a version as {column_name: type_string}."""
        ...

    def added_rows_at(self, version: int) -> int:
        """Row count *added* by a version, from metadata stats (O(1))."""
        ...

    def added_data_files_at(self, version: int) -> List[str]:
        """Absolute paths of data files added by a version (for O(Δ) scans)."""
        ...

    def read_data_files(self, paths: List[str]) -> pa.Table:
        """Read the given data files into a single PyArrow table."""
        ...


# ---------------------------------------------------------------------------
# Delta Lake reader — reads the _delta_log JSON directly (no Spark).
# ---------------------------------------------------------------------------


class DeltaReader:
    format = LakehouseFormat.DELTA

    def __init__(self, table_path: str):
        self.table_path = table_path.rstrip("/")

    def _log_json(self, version: int) -> List[Dict[str, Any]]:
        log_path = storage.join_path(self.table_path, "_delta_log", f"{version:020d}.json")
        if not storage.exists(log_path):
            raise ValueError(f"Delta log for version {version} not found at {log_path}")
        lines = storage.read_text(log_path).splitlines()
        return [json.loads(line) for line in lines if line.strip()]

    def latest_version(self) -> int:
        log_dir = storage.join_path(self.table_path, "_delta_log")
        if not storage.exists(log_dir):
            raise ValueError(f"No _delta_log found at {self.table_path}")
        max_v = -1
        for f in storage.list_dir(log_dir):
            if f.endswith(".json") and len(f) == 25:
                try:
                    max_v = max(max_v, int(f.replace(".json", "")))
                except ValueError:
                    continue
        if max_v == -1:
            raise ValueError(f"No commit json files found in {log_dir}")
        return max_v

    def schema_at(self, version: int) -> Dict[str, str]:
        # Traverse backwards to the most recent metaData action at/before version.
        for v in range(version, -1, -1):
            try:
                actions = self._log_json(v)
            except ValueError:
                continue
            for action in actions:
                if "metaData" in action:
                    schema = json.loads(action["metaData"]["schemaString"])
                    return {f["name"]: _delta_type_str(f["type"]) for f in schema.get("fields", [])}
        raise ValueError(f"No metaData action found at or before version {version}")

    def added_rows_at(self, version: int) -> int:
        total = 0
        for action in self._log_json(version):
            add = action.get("add")
            if add and add.get("stats"):
                total += json.loads(add["stats"]).get("numRecords", 0)
        return total

    def added_data_files_at(self, version: int) -> List[str]:
        import urllib.parse

        paths = []
        for action in self._log_json(version):
            add = action.get("add")
            if add:
                paths.append(storage.join_path(self.table_path, urllib.parse.unquote(add["path"])))
        return paths

    def read_data_files(self, paths: List[str]) -> pa.Table:
        return storage.read_parquet(paths)


def _delta_type_str(dtype: Any) -> str:
    """Delta schema types are either a string or a nested dict; stringify simply."""
    if isinstance(dtype, str):
        return dtype
    if isinstance(dtype, dict):
        return dtype.get("type", "complex")
    return str(dtype)


# ---------------------------------------------------------------------------
# Iceberg reader — reads table metadata + manifest snapshots via PyIceberg.
# ---------------------------------------------------------------------------


class IcebergReader:
    """
    Reads Iceberg tables through PyIceberg's StaticTable (metadata.json only — no
    catalog needed). "version N" maps to the N-th snapshot in chronological order,
    so version_n vs version_n-1 compares consecutive snapshots, matching the Delta
    semantics the checks expect.
    """

    format = LakehouseFormat.ICEBERG

    def __init__(self, table_path: str):
        self.table_path = table_path.rstrip("/")
        self._table = None
        self._snapshots = None

    def _load(self):
        if self._table is None:
            from pyiceberg.table import StaticTable

            metadata_file = self._latest_metadata_file()
            properties = {}

            endpoint = os.environ.get("AWS_ENDPOINT_URL")
            if endpoint:
                properties["s3.endpoint"] = endpoint

            access_key = os.environ.get("AWS_ACCESS_KEY_ID")
            if access_key:
                properties["s3.access-key-id"] = access_key

            secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY")
            if secret_key:
                properties["s3.secret-access-key"] = secret_key

            properties["s3.region"] = os.environ.get("AWS_REGION") or "us-east-1"

            self._table = StaticTable.from_metadata(metadata_file, properties)
            # Snapshots in chronological order; index == our "version".
            self._snapshots = list(self._table.metadata.snapshots)
        return self._table

    def _latest_metadata_file(self) -> str:
        """Find the newest vN.metadata.json under metadata/ (highest version)."""
        meta_dir = storage.join_path(self.table_path, "metadata")
        candidates = [f for f in storage.list_dir(meta_dir) if f.endswith(".metadata.json")]
        if not candidates:
            raise ValueError(f"No *.metadata.json found under {meta_dir}")

        # Names look like 00003-<uuid>.metadata.json → sort by the numeric prefix.
        def _rank(name: str) -> int:
            head = name.split("-", 1)[0]
            return int(head) if head.isdigit() else -1

        latest = max(candidates, key=_rank)
        return storage.join_path(meta_dir, latest)

    def latest_version(self) -> int:
        self._load()
        if not self._snapshots:
            raise ValueError(f"Iceberg table at {self.table_path} has no snapshots")
        return len(self._snapshots) - 1

    def _snapshot(self, version: int):
        self._load()
        if version < 0 or version >= len(self._snapshots):
            raise ValueError(f"Snapshot version {version} out of range")
        return self._snapshots[version]

    def schema_at(self, version: int) -> Dict[str, str]:
        table = self._load()
        snap = self._snapshot(version)
        schema_id = (
            snap.schema_id if snap.schema_id is not None else table.metadata.current_schema_id
        )
        schema = next(
            (s for s in table.metadata.schemas if s.schema_id == schema_id),
            table.schema(),
        )
        return {f.name: str(f.field_type) for f in schema.fields}

    def added_rows_at(self, version: int) -> int:
        snap = self._snapshot(version)
        summary = snap.summary
        if summary is None:
            return 0
        props = summary.additional_properties if hasattr(summary, "additional_properties") else {}
        return int(props.get("added-records", 0))

    def added_data_files_at(self, version: int) -> List[str]:
        """
        Files added in this snapshot = files in this snapshot's manifests whose
        added-snapshot-id equals this snapshot's id.
        """
        table = self._load()
        snap = self._snapshot(version)
        io = table.io
        paths: List[str] = []
        for manifest in snap.manifests(io):
            for entry in manifest.fetch_manifest_entry(io, discard_deleted=True):
                added_sid = getattr(entry, "snapshot_id", None)
                if added_sid in (None, snap.snapshot_id):
                    paths.append(entry.data_file.file_path)
        return paths

    def read_data_files(self, paths: List[str]) -> pa.Table:
        return storage.read_parquet(paths)


# ---------------------------------------------------------------------------
# Factory + auto-detection
# ---------------------------------------------------------------------------


def detect_format(table_path: str) -> LakehouseFormat:
    """
    Auto-detect table format by layout:
    - a ``_delta_log/`` directory  → Delta
    - a ``metadata/`` dir with ``*.metadata.json`` → Iceberg
    """
    if storage.exists(storage.join_path(table_path, "_delta_log")):
        return LakehouseFormat.DELTA
    meta_dir = storage.join_path(table_path, "metadata")
    if storage.exists(meta_dir):
        try:
            if any(f.endswith(".metadata.json") for f in storage.list_dir(meta_dir)):
                return LakehouseFormat.ICEBERG
        except Exception:  # noqa: S110 - detection is best-effort; fall through to error below
            pass
    raise ValueError(
        f"Could not detect table format at {table_path}: no _delta_log/ (Delta) "
        f"or metadata/*.metadata.json (Iceberg) found. Pass --format explicitly."
    )


def get_reader(table_path: str, format_value: str = None) -> MetadataReader:
    """Build the reader for an explicit format, or auto-detect when None."""
    if format_value:
        fmt = LakehouseFormat(format_value.strip().lower())
    else:
        fmt = detect_format(table_path)
    if fmt == LakehouseFormat.DELTA:
        return DeltaReader(table_path)
    return IcebergReader(table_path)
