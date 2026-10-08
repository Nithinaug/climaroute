"""The only place that touches files or S3.

DATA_BUCKET unset -> ./data/<key> (local dev). DATA_BUCKET set -> s3://<bucket>/<key>.
A missing key raises FileNotFoundError in both modes.
"""

import os
from functools import cache
from pathlib import Path

LOCAL_ROOT = Path("data")


@cache
def _s3():
    import boto3  # preinstalled in the Lambda base image; not needed for local dev

    return boto3.client("s3")


def read_bytes(key: str) -> bytes:
    bucket = os.environ.get("DATA_BUCKET")
    if not bucket:
        return (LOCAL_ROOT / key).read_bytes()
    try:
        return _s3().get_object(Bucket=bucket, Key=key)["Body"].read()
    except _s3().exceptions.NoSuchKey as e:
        raise FileNotFoundError(f"s3://{bucket}/{key}") from e


def write_bytes(key: str, data: bytes) -> None:
    bucket = os.environ.get("DATA_BUCKET")
    if not bucket:
        path = LOCAL_ROOT / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return
    _s3().put_object(Bucket=bucket, Key=key, Body=data)


def version(key: str) -> str:
    """Changes whenever the stored file changes (S3 ETag, or local mtime). Cheap: no download."""
    bucket = os.environ.get("DATA_BUCKET")
    if not bucket:
        return str((LOCAL_ROOT / key).stat().st_mtime_ns)
    try:
        return _s3().head_object(Bucket=bucket, Key=key)["ETag"]
    except _s3().exceptions.ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchKey"):
            raise FileNotFoundError(f"s3://{bucket}/{key}") from e
        raise
