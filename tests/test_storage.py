import pytest

from shared.storage import read_bytes, write_bytes


def test_roundtrip_creates_folders(local_data):
    write_bytes("a/b/c.bin", b"hi")
    assert read_bytes("a/b/c.bin") == b"hi"


def test_missing_key_raises(local_data):
    with pytest.raises(FileNotFoundError):
        read_bytes("nope.json")
