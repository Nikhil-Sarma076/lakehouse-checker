from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class SchemaDiff:
    added_columns: List[str] = field(default_factory=list)
    removed_columns: List[str] = field(default_factory=list)
    type_changes: Dict[str, str] = field(default_factory=dict)

    def has_drift(self) -> bool:
        return bool(self.added_columns or self.removed_columns or self.type_changes)


@dataclass
class RowCountDiff:
    version_n_added_rows: int
    version_n_minus_1_added_rows: int
    percentage_change: float
    exceeds_threshold: bool


@dataclass
class NullSpikeResult:
    column: str
    version_n_null_pct: float
    version_n_minus_1_null_pct: float
    spike_detected: bool


@dataclass
class DuplicatePKResult:
    has_duplicates: bool
    duplicate_count: int
