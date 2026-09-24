from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError

from lakecheck import storage
from lakecheck.readers import DeltaReader


def test_join_path():
    assert (
        storage.join_path("s3://bucket/table", "_delta_log", "0000.json")
        == "s3://bucket/table/_delta_log/0000.json"
    )
    assert (
        storage.join_path("s3a://bucket/table", "file.parquet") == "s3a://bucket/table/file.parquet"
    )
    assert "local/dir" in storage.join_path("local", "dir").replace("\\", "/")


@patch("lakecheck.storage.boto3")
def test_s3_read_text(mock_boto3):
    mock_client = MagicMock()
    mock_boto3.client.return_value = mock_client

    mock_body = MagicMock()
    mock_body.read.return_value = b'{"commitInfo": {}}'
    mock_client.get_object.return_value = {"Body": mock_body}

    content = storage.read_text("s3://my-bucket/path/to/log.json")

    mock_client.get_object.assert_called_once_with(Bucket="my-bucket", Key="path/to/log.json")
    assert content == '{"commitInfo": {}}'


@patch("lakecheck.storage.boto3")
def test_s3_list_dir(mock_boto3):
    mock_client = MagicMock()
    mock_boto3.client.return_value = mock_client

    mock_paginator = MagicMock()
    mock_client.get_paginator.return_value = mock_paginator

    mock_paginator.paginate.return_value = [
        {
            "Contents": [
                {"Key": "table/_delta_log/"},
                {"Key": "table/_delta_log/00000000000000000000.json"},
                {"Key": "table/_delta_log/00000000000000000001.json"},
            ]
        }
    ]

    files = storage.list_dir("s3://my-bucket/table/_delta_log")

    assert len(files) == 2
    assert "00000000000000000000.json" in files
    assert "00000000000000000001.json" in files


@patch("lakecheck.storage.boto3")
def test_delta_reader_latest_version_s3(mock_boto3):
    """DeltaReader.latest_version scans _delta_log/*.json for the max version (O(1))."""
    mock_client = MagicMock()
    mock_boto3.client.return_value = mock_client

    # exists(_delta_log) → head_object 404 then list_objects finds contents.
    mock_client.head_object.side_effect = ClientError(
        {"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject"
    )
    mock_client.list_objects_v2.return_value = {"Contents": [{"Key": "x"}]}

    mock_paginator = MagicMock()
    mock_client.get_paginator.return_value = mock_paginator
    mock_paginator.paginate.return_value = [
        {
            "Contents": [
                {"Key": "table/_delta_log/00000000000000000000.json"},
                {"Key": "table/_delta_log/00000000000000000005.json"},
            ]
        }
    ]

    version = DeltaReader("s3://my-bucket/table").latest_version()
    assert version == 5
