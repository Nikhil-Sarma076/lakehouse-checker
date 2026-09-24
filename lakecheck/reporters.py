import json
import urllib.request
from dataclasses import asdict, dataclass
from typing import List, Optional, Protocol

from lakecheck.models import DuplicatePKResult, NullSpikeResult, RowCountDiff, SchemaDiff


@dataclass
class CheckResults:
    table_path: str
    version: int
    schema_diff: SchemaDiff
    row_count_diff: RowCountDiff
    null_spikes: List[NullSpikeResult]
    duplicate_pks: Optional[DuplicatePKResult]
    format: str = "delta"

    @property
    def has_anomalies(self) -> bool:
        if self.schema_diff.has_drift():
            return True
        if self.row_count_diff.exceeds_threshold:
            return True
        if any(ns.spike_detected for ns in self.null_spikes):
            return True
        if self.duplicate_pks and self.duplicate_pks.has_duplicates:
            return True
        return False


class Reporter(Protocol):
    def report(self, results: CheckResults) -> None: ...


class TerminalReporter:
    RED = "\033[91m"
    GREEN = "\033[92m"
    RESET = "\033[0m"

    def report(self, results: CheckResults) -> None:
        red, green, reset = self.RED, self.GREEN, self.RESET
        rcd = results.row_count_diff

        print(
            f"\nlakecheck Report [{results.format}] for {results.table_path} "
            f"(Version {results.version})"
        )
        print("=" * 60)

        if results.schema_diff.has_drift():
            print(f"{red}✖ Schema Drift Detected{reset}")
            if results.schema_diff.added_columns:
                print(f"  Added: {results.schema_diff.added_columns}")
            if results.schema_diff.removed_columns:
                print(f"  Removed: {results.schema_diff.removed_columns}")
            if results.schema_diff.type_changes:
                print(f"  Type Changes: {results.schema_diff.type_changes}")
        else:
            print(f"{green}✔ No Schema Drift{reset}")

        if rcd.exceeds_threshold:
            print(f"{red}✖ Row Count Drop Detected ({rcd.percentage_change:.2f}%){reset}")
        else:
            print(f"{green}✔ Row Count Stable ({rcd.percentage_change:.2f}%){reset}")

        for ns in results.null_spikes:
            if ns.spike_detected:
                print(
                    f"{red}✖ Null Spike in '{ns.column}' "
                    f"({ns.version_n_null_pct:.1f}% vs {ns.version_n_minus_1_null_pct:.1f}%){reset}"
                )
            else:
                print(f"{green}✔ Nulls stable in '{ns.column}'{reset}")

        if results.duplicate_pks:
            dp = results.duplicate_pks
            if dp.has_duplicates:
                print(f"{red}✖ Duplicate PKs Detected ({dp.duplicate_count} duplicates){reset}")
            else:
                print(f"{green}✔ No Duplicate PKs introduced{reset}")
        print("=" * 60 + "\n")


class JSONReporter:
    def report(self, results: CheckResults) -> None:
        payload = asdict(results)
        payload["has_anomalies"] = results.has_anomalies
        print(json.dumps(payload))


class SlackReporter:
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def report(self, results: CheckResults) -> None:
        if not results.has_anomalies:
            return

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"🚨 lakecheck Anomalies [{results.format}]: {results.table_path}",
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*Version:* {results.version}\n"
                        "Anomalies were detected in the latest commit."
                    ),
                },
            },
        ]

        payload = {"blocks": blocks}
        req = urllib.request.Request(  # noqa: S310 - stdlib per design philosophy
            self.webhook_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )

        try:
            urllib.request.urlopen(req)  # noqa: S310 - stdlib per design philosophy
        except Exception as e:
            print(f"Warning: Failed to send Slack alert: {e}")
