"""Append source access attempts to docs/source_access_log.csv."""

import csv
from datetime import date

from scoreboard.config import PROJECT_ROOT

ACCESS_LOG = PROJECT_ROOT / "docs" / "source_access_log.csv"
COLUMNS = ["date", "source", "url_tested", "result", "notes"]


def log_access(source: str, url_tested: str, result: str, notes: str = "", when: str | None = None, path=ACCESS_LOG) -> None:
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if new:
            writer.writerow(COLUMNS)
        writer.writerow([when or date.today().isoformat(), source, url_tested, result, notes])
