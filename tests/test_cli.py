import sys
from unittest.mock import MagicMock, patch

import pytest

from lakecheck.cli import main
from lakecheck.models import DuplicatePKResult, RowCountDiff, SchemaDiff
from lakecheck.readers import LakehouseFormat


@pytest.fixture
def clean_engine_mocks():
    """Patch the reader factory + all four checks so the CLI runs with no real table."""
    fake_reader = MagicMock()
    fake_reader.format = LakehouseFormat.DELTA
    fake_reader.latest_version.return_value = 1
    with (
        patch("lakecheck.cli.get_reader", return_value=fake_reader) as m_reader,
        patch("lakecheck.cli.check_schema_drift", return_value=SchemaDiff()) as m_schema,
        patch(
            "lakecheck.cli.check_row_count_drop", return_value=RowCountDiff(10, 10, 0.0, False)
        ) as m_row,
        patch("lakecheck.cli.check_null_spikes", return_value=[]) as m_null,
        patch(
            "lakecheck.cli.check_duplicate_pks", return_value=DuplicatePKResult(False, 0)
        ) as m_pk,
    ):
        yield {
            "reader": m_reader,
            "schema": m_schema,
            "row": m_row,
            "null": m_null,
            "pk": m_pk,
        }


def test_clean_table_exits_zero(clean_engine_mocks):
    with patch.object(sys, "argv", ["lakecheck", "s3://my-bucket/table"]):
        with pytest.raises(SystemExit) as exc:
            main()
    assert exc.value.code == 0
    # O(Δ) checks skipped when no --pk / --check-nulls supplied.
    clean_engine_mocks["null"].assert_not_called()
    clean_engine_mocks["pk"].assert_not_called()


def test_odelta_checks_run_when_flags_present(clean_engine_mocks):
    with patch.object(sys, "argv", ["lakecheck", "table", "--pk", "id", "--check-nulls", "email"]):
        with pytest.raises(SystemExit):
            main()
    clean_engine_mocks["null"].assert_called_once()
    clean_engine_mocks["pk"].assert_called_once()


def test_format_flag_passed_to_reader(clean_engine_mocks):
    with patch.object(sys, "argv", ["lakecheck", "table", "--format", "iceberg"]):
        with pytest.raises(SystemExit):
            main()
    # get_reader receives the explicit format.
    _, kwargs = clean_engine_mocks["reader"].call_args
    args = clean_engine_mocks["reader"].call_args[0]
    assert (
        "iceberg" in args
        or kwargs.get("format_value") == "iceberg"
        or "iceberg" in str(clean_engine_mocks["reader"].call_args)
    )


@patch("lakecheck.cli.JSONReporter")
@patch("lakecheck.cli.TerminalReporter")
@patch("lakecheck.cli.SlackReporter")
def test_reporters_and_slack_webhook(mock_slack, mock_term, mock_json, clean_engine_mocks):
    argv = ["lakecheck", "table", "--json", "--slack-webhook", "https://hooks.slack.com/foo"]
    with patch.object(sys, "argv", argv):
        with pytest.raises(SystemExit):
            main()
    mock_json.assert_called_once()
    mock_term.assert_not_called()
    mock_slack.assert_called_once_with("https://hooks.slack.com/foo")


def test_exit_code_on_anomalies(clean_engine_mocks):
    clean_engine_mocks["schema"].return_value = SchemaDiff(added_columns=["evil_col"])
    with patch.object(sys, "argv", ["lakecheck", "table"]):
        with pytest.raises(SystemExit) as exc:
            main()
    assert exc.value.code == 1
