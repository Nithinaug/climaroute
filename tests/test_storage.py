import pytest

from shared.storage import read_bytes, write_bytes


def test_roundtrip_creates_folders(local_data):
    write_bytes("a/b/c.bin", b"hi")
    assert read_bytes("a/b/c.bin") == b"hi"


def test_missing_key_raises(local_data):
    with pytest.raises(FileNotFoundError):
        read_bytes("nope.json")


def test_version_changes_when_the_file_changes(local_data):
    import time

    from shared.storage import version, write_bytes

    write_bytes("graph/x.npz", b"a")
    v1 = version("graph/x.npz")
    time.sleep(0.01)
    write_bytes("graph/x.npz", b"b")
    assert version("graph/x.npz") != v1
    with pytest.raises(FileNotFoundError):
        version("graph/missing.npz")
