"""Load the collection configuration from config/collection.yaml."""

from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "collection.yaml"


def load_config(path: Path | str = DEFAULT_CONFIG_PATH) -> dict:
    """Return the collection configuration as a dictionary."""
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)
