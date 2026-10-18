"""Append source access attempts to docs/source_access_log.csv."""

import csv
import threading
from datetime import date

from scoreboard.config import PROJECT_ROOT

ACCESS_LOG = PROJECT_ROOT / "docs" / "source_access_log.csv"
COLUMNS = ["date", "source", "url_tested", "result", "notes"]
# Domain workers run in threads; one writer at a time keeps rows whole.
_LOCK = threading.Lock()


def log_access(source: str, url_tested: str, result: str, notes: str = "", when: str | None = None, path=None) -> None:
    # ACCESS_LOG is read at call time, so tests can point it at a temporary file.
    with _LOCK:
        _append(source, url_tested, result, notes, when, path or ACCESS_LOG)


def _append(source, url_tested, result, notes, when, path) -> None:
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if new:
            writer.writerow(COLUMNS)
        writer.writerow([when or date.today().isoformat(), source, url_tested, result, notes])
