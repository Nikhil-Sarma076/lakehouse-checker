from unittest.mock import patch

import pytest

from lakecheck.models import RowCountDiff, SchemaDiff
from lakecheck.reporters import CheckResults, SlackReporter


@pytest.fixture
def clean_results():
    return CheckResults(
        table_path="s3://dummy",
        version=1,
        schema_diff=SchemaDiff(),
        row_count_diff=RowCountDiff(10, 10, 0.0, False),
        null_spikes=[],
        duplicate_pks=None,
    )


@pytest.fixture
def dirty_results():
    return CheckResults(
        table_path="s3://dummy",
        version=1,
        schema_diff=SchemaDiff(added_columns=["evil_col"]),
        row_count_diff=RowCountDiff(10, 10, 0.0, False),
        null_spikes=[],
        duplicate_pks=None,
    )


@patch("urllib.request.urlopen")
def test_slack_reporter_skips_clean(mock_urlopen, clean_results):
    reporter = SlackReporter("http://fake-webhook")
    reporter.report(clean_results)
    mock_urlopen.assert_not_called()


@patch("urllib.request.urlopen")
def test_slack_reporter_fires_dirty(mock_urlopen, dirty_results):
    reporter = SlackReporter("http://fake-webhook")
    reporter.report(dirty_results)
    mock_urlopen.assert_called_once()

    request_obj = mock_urlopen.call_args[0][0]
    payload = request_obj.data.decode("utf-8")
    assert "s3://dummy" in payload
