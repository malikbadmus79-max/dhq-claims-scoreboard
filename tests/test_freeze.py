import hashlib
import re

import pandas as pd
import pytest

from scoreboard.config import PROJECT_ROOT

FREEZE_RECORD = PROJECT_ROOT / "docs" / "freeze_v1.0.md"
ROW_RE = re.compile(r"^\| (data/\S+\.csv) \| (\d+) \| ([0-9a-f]{64}) \|$", re.M)
FROZEN = ROW_RE.findall(FREEZE_RECORD.read_text(encoding="utf-8"))


def lf_sha256(path) -> str:
    """SHA-256 of the file as git stores it (eol=lf), whatever the working copy's line endings."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def test_freeze_record_lists_the_six_files():
    assert len(FROZEN) == 6 and len({f for f, _, _ in FROZEN}) == 6


@pytest.mark.parametrize("path,rows,checksum", FROZEN, ids=[f for f, _, _ in FROZEN])
def test_frozen_file_is_unchanged(path, rows, checksum):
    file = PROJECT_ROOT / path
    assert lf_sha256(file) == checksum, f"{path} changed after the v1.0 freeze; log it under Deviations"
    assert len(pd.read_csv(file, keep_default_na=False, dtype=str)) == int(rows)


def test_checksum_ignores_line_endings(tmp_path):
    lf, crlf = tmp_path / "lf.csv", tmp_path / "crlf.csv"
    lf.write_bytes(b"a,b\n1,2\n")
    crlf.write_bytes(b"a,b\r\n1,2\r\n")
    assert lf_sha256(lf) == lf_sha256(crlf) == hashlib.sha256(b"a,b\n1,2\n").hexdigest()
