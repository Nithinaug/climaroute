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
