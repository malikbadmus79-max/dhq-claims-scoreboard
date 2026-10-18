import pytest

from scoreboard.config import load_config
from scoreboard.fetch import Fetcher


class FakeResponse:
    def __init__(self, status_code=200, text="", headers=None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}


class FakeSession:
    def __init__(self, routes):
        self.routes = routes
        self.headers = {}
        self.calls = []

    def get(self, url, timeout=None):
        self.calls.append(url)
        return self.routes.get(url, FakeResponse(404))


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def make_fetcher(tmp_path, routes, clock=None):
    clock = clock or FakeClock()
    session = FakeSession(routes)
    fetcher = Fetcher(load_config(), cache_dir=tmp_path, session=session, clock=clock, sleep=clock.sleep)
    return fetcher, session, clock


ROBOTS_OK = {"https://example.org/robots.txt": FakeResponse(200, "User-agent: *\nDisallow: /private\n")}


def test_user_agent_set(tmp_path):
    fetcher, session, _ = make_fetcher(tmp_path, ROBOTS_OK)
    assert session.headers["User-Agent"] == load_config()["user_agent"]


def test_cache_hit_makes_no_request(tmp_path):
    routes = {**ROBOTS_OK, "https://example.org/a": FakeResponse(200, "body")}
    fetcher, session, _ = make_fetcher(tmp_path, routes)
    assert fetcher.get("https://example.org/a").text == "body"

    second, second_session, _ = make_fetcher(tmp_path, {})
    resp = second.get("https://example.org/a")
    assert resp.text == "body" and resp.from_cache
    assert second_session.calls == []


def test_robots_disallow_skips_request(tmp_path):
    fetcher, session, _ = make_fetcher(tmp_path, ROBOTS_OK)
    assert fetcher.get("https://example.org/private/page") is None
    assert session.calls == ["https://example.org/robots.txt"]


def test_delay_respected_per_domain(tmp_path):
    routes = {
        **ROBOTS_OK,
        "https://example.org/a": FakeResponse(200, "a"),
        "https://example.org/b": FakeResponse(200, "b"),
    }
    fetcher, session, clock = make_fetcher(tmp_path, routes)
    times = []
    original = session.get

    def timed_get(url, timeout=None):
        times.append(clock.now)
        return original(url, timeout)

    session.get = timed_get
    fetcher.get("https://example.org/a")
    fetcher.get("https://example.org/b")
    assert len(times) == 3
    gaps = [b - a for a, b in zip(times, times[1:])]
    assert all(gap >= 5 for gap in gaps)


def test_retries_then_succeeds(tmp_path):
    responses = iter([FakeResponse(503), FakeResponse(200, "ok")])
    routes = dict(ROBOTS_OK)
    fetcher, session, _ = make_fetcher(tmp_path, routes)
    original = session.get

    def flaky(url, timeout=None):
        if url == "https://example.org/r":
            session.calls.append(url)
            return next(responses)
        return original(url, timeout)

    session.get = flaky
    assert fetcher.get("https://example.org/r").text == "ok"
    assert session.calls.count("https://example.org/r") == 2


@pytest.mark.parametrize("status", [401, 403])
def test_robots_forbidden_disallows_all(tmp_path, status):
    routes = {"https://example.org/robots.txt": FakeResponse(status)}
    fetcher, session, _ = make_fetcher(tmp_path, routes)
    assert fetcher.get("https://example.org/a") is None


def test_offline_mode_never_requests(tmp_path):
    from scoreboard.fetch import OFFLINE_MISS

    clock = FakeClock()
    session = FakeSession(ROBOTS_OK)
    fetcher = Fetcher(load_config(), cache_dir=tmp_path, session=session, clock=clock, sleep=clock.sleep, offline=True)
    assert fetcher.get("https://example.org/a") is None
    assert fetcher.skip_reason == OFFLINE_MISS
    assert session.calls == []


def test_check_robots_reports_status_and_permission(tmp_path):
    fetcher, session, _ = make_fetcher(tmp_path, ROBOTS_OK)
    assert fetcher.check_robots("https://example.org/wp-json/wp/v2/posts") == (True, "HTTP 200")
    assert fetcher.check_robots("https://example.org/private/x") == (False, "HTTP 200")
    assert session.calls == ["https://example.org/robots.txt"]


def test_check_robots_unreachable(tmp_path):
    routes = {"https://down.example/robots.txt": FakeResponse(503)}
    fetcher, _, _ = make_fetcher(tmp_path, routes)
    assert fetcher.check_robots("https://down.example/") == (False, "unreachable")
