import pytest


@pytest.fixture
def local_data(tmp_path, monkeypatch):
    """Run storage against an empty temp ./data directory."""
    monkeypatch.delenv("DATA_BUCKET", raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path / "data"
