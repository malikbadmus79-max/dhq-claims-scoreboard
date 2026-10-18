import pytest

import scoreboard.access_log as access_log


@pytest.fixture(autouse=True)
def isolated_access_log(tmp_path, monkeypatch):
    """No test writes to docs/source_access_log.csv: every log row goes to a temporary file."""
    path = tmp_path / "source_access_log.csv"
    monkeypatch.setattr(access_log, "ACCESS_LOG", path)
    return path
