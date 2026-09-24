import os
import posixpath
from typing import List
from urllib.parse import urlparse

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:
    boto3 = None
    ClientError = Exception


def is_s3(path: str) -> bool:
    """Check if the path is an S3 URI."""
    return path.startswith("s3://") or path.startswith("s3a://")


def _local(path: str) -> str:
    """Strip a file:// scheme so os.* functions get a plain filesystem path."""
    if path.startswith("file://"):
        return urlparse(path).path
    return path


def parse_s3_path(path: str) -> tuple[str, str]:
    """Extract bucket and key from an S3 URI."""
    parsed = urlparse(path)
    return parsed.netloc, parsed.path.lstrip("/")


def read_text(path: str) -> str:
    """Read file contents as a string."""
    if is_s3(path):
        if boto3 is None:
            raise ImportError("boto3 is required for S3 support")
        s3 = boto3.client("s3")
        bucket, key = parse_s3_path(path)
        response = s3.get_object(Bucket=bucket, Key=key)
        return response["Body"].read().decode("utf-8")
    else:
        with open(_local(path), "r", encoding="utf-8") as f:
            return f.read()


def list_dir(path: str) -> List[str]:
    """List filenames in a directory (non-recursive)."""
    if is_s3(path):
        if boto3 is None:
            raise ImportError("boto3 is required for S3 support")
        s3 = boto3.client("s3")
        bucket, prefix = parse_s3_path(path)
        if not prefix.endswith("/"):
            prefix += "/"

        paginator = s3.get_paginator("list_objects_v2")
        files = []
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if key != prefix:
                    basename = key[len(prefix) :].split("/")[0]
                    if basename:
                        files.append(basename)
        return list(set(files))
    else:
        return os.listdir(_local(path))


def exists(path: str) -> bool:
    """Check if a file or directory prefix exists."""
    if is_s3(path):
        if boto3 is None:
            raise ImportError("boto3 is required for S3 support")
        s3 = boto3.client("s3")
        bucket, key = parse_s3_path(path)

        try:
            s3.head_object(Bucket=bucket, Key=key)
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                prefix = key if key.endswith("/") else key + "/"
                res = s3.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=1)
                return "Contents" in res
            raise
    else:
        return os.path.exists(_local(path))


def read_parquet(paths: List[str]):
    """
    Read one or more Parquet data files into a single PyArrow table — the O(Δ)
    scan primitive. Works for local paths and s3://,s3a:// via pyarrow's S3
    filesystem (zero-JVM; no Spark). Credentials/endpoint come from the standard
    AWS_* env vars, matching how the checker runs in a CronJob / locally.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    if not paths:
        return pa.table({})

    if is_s3(paths[0]):
        import os

        import pyarrow.fs as pafs

        endpoint = os.environ.get("AWS_ENDPOINT_URL", "")
        fs = pafs.S3FileSystem(
            access_key=os.environ.get("AWS_ACCESS_KEY_ID"),
            secret_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
            region=os.environ.get("AWS_REGION") or "us-east-1",
            endpoint_override=(endpoint.replace("http://", "").replace("https://", "") or None),
            scheme="http" if endpoint.startswith("http://") else "https",
        )
        # pyarrow S3FS wants "bucket/key" without the scheme prefix.
        fs_paths = [p.split("://", 1)[1] for p in paths]
        tables = [pq.read_table(p, filesystem=fs) for p in fs_paths]
    else:
        tables = [pq.read_table(_local(p)) for p in paths]

    return tables[0] if len(tables) == 1 else pa.concat_tables(tables, promote_options="default")


def join_path(base: str, *parts: str) -> str:
    """Safely join paths, preserving S3 scheme and forward slashes."""
    if is_s3(base):
        parsed = urlparse(base)
        joined_path = posixpath.join(parsed.path.lstrip("/"), *parts)
        return f"{parsed.scheme}://{parsed.netloc}/{joined_path}"
    else:
        return os.path.join(base, *parts)
