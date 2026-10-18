import datetime

from scoreboard.config import load_config


def test_config_loads():
    config = load_config()
    assert config["date_range"]["start"] == datetime.date(2021, 1, 1)
    assert config["date_range"]["end"] == datetime.date(2026, 10, 31)
    assert "github.com/malikbadmus79-max/dhq-claims-scoreboard" in config["user_agent"]
    assert len(config["outlets"]) == 14


def test_delay_at_least_five_seconds():
    assert load_config()["min_delay_seconds"] >= 5


def test_robots_txt_obeyed():
    assert load_config()["obey_robots_txt"] is True


def test_outlet_domains_present_and_unique():
    domains = [outlet.get("domain") for outlet in load_config()["outlets"]]
    assert all(domains)
    assert len(domains) == len(set(domains))
