import argparse
import sys
from typing import List

from lakecheck.engine import (
    check_duplicate_pks,
    check_null_spikes,
    check_row_count_drop,
    check_schema_drift,
)
from lakecheck.readers import get_reader
from lakecheck.reporters import (
    CheckResults,
    JSONReporter,
    Reporter,
    SlackReporter,
    TerminalReporter,
)


def main():
    parser = argparse.ArgumentParser(
        description="Lightweight, zero-JVM data-quality checks for Delta Lake and Apache Iceberg."
    )
    parser.add_argument("table_path", help="Path to the table (local or s3:// / s3a://)")
    parser.add_argument(
        "--format",
        choices=["delta", "iceberg"],
        help="Table format. Auto-detected from the table layout when omitted.",
    )
    parser.add_argument("--version", type=int, help="Target version N. Defaults to latest.")
    parser.add_argument("--pk", help="Primary key column(s) for duplicate check (comma-separated)")
    parser.add_argument("--check-nulls", help="Columns to check for null spikes (comma-separated)")
    parser.add_argument("--slack-webhook", help="Slack webhook URL for anomaly alerts")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")

    args = parser.parse_args()

    table_path = args.table_path
    # Delta on S3 needs the s3a scheme for the Hadoop-style path convention the
    # _delta_log uses; Iceberg/PyIceberg is happy with either. Normalize for Delta.
    if table_path.startswith("s3://") and (args.format == "delta" or args.format is None):
        # Only rewrite when it actually is a Delta table; detection handles the rest.
        pass

    try:
        reader = get_reader(table_path, args.format)
    except Exception as e:
        print(f"Error opening table: {e}")
        sys.exit(1)

    try:
        version = args.version if args.version is not None else reader.latest_version()
    except Exception as e:
        print(f"Error determining version: {e}")
        sys.exit(1)

    if version == 0:
        print("Table is at version 0. Nothing to compare against.")
        sys.exit(0)

    pk_columns = args.pk.split(",") if args.pk else []
    null_columns = args.check_nulls.split(",") if args.check_nulls else []

    schema_diff = check_schema_drift(reader, version)
    row_count_diff = check_row_count_drop(reader, version)

    null_spikes = []
    if null_columns:
        null_spikes = check_null_spikes(reader, version, null_columns)

    duplicate_pks = None
    if pk_columns:
        duplicate_pks = check_duplicate_pks(reader, version, pk_columns)

    results = CheckResults(
        table_path=args.table_path,
        version=version,
        schema_diff=schema_diff,
        row_count_diff=row_count_diff,
        null_spikes=null_spikes,
        duplicate_pks=duplicate_pks,
        format=str(reader.format.value),
    )

    reporters: List[Reporter] = []
    if args.json:
        reporters.append(JSONReporter())
    else:
        reporters.append(TerminalReporter())

    if args.slack_webhook:
        reporters.append(SlackReporter(args.slack_webhook))

    for reporter in reporters:
        reporter.report(results)

    sys.exit(1 if results.has_anomalies else 0)


if __name__ == "__main__":
    main()
