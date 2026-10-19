import json
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


# Per-domain delays and HTTP 429


class SequenceSession(FakeSession):
    """Serves a list of responses per URL, one per request, repeating the last."""

    def get(self, url, timeout=None):
        self.calls.append(url)
        seq = self.routes.get(url)
        if seq is None:
            return FakeResponse(404)
        return seq.pop(0) if len(seq) > 1 else seq[0]


def make_seq_fetcher(tmp_path, routes, config=None):
    clock = FakeClock()
    session = SequenceSession(routes)
    fetcher = Fetcher(config or load_config(), cache_dir=tmp_path, session=session, clock=clock, sleep=clock.sleep)
    return fetcher, session, clock


def test_domain_delay_for_wayback_and_default_elsewhere(tmp_path):
    fetcher, _, _ = make_fetcher(tmp_path, ROBOTS_OK)
    assert fetcher.delay_for("archive.org") == 15
    assert fetcher.delay_for("web.archive.org") == 15
    assert fetcher.delay_for("www.archive.org") == 15
    assert fetcher.delay_for("blueprint.ng") == 5


def test_domain_delay_applied_between_requests(tmp_path):
    routes = {
        "https://archive.org/robots.txt": FakeResponse(200, ""),
        "https://archive.org/a": FakeResponse(200, "a"),
        "https://archive.org/b": FakeResponse(200, "b"),
    }
    fetcher, _, clock = make_fetcher(tmp_path, routes)
    fetcher.get("https://archive.org/a")
    fetcher.get("https://archive.org/b")
    assert clock.sleeps == [15, 15]


def test_429_obeys_retry_after_and_retries_once(tmp_path, isolated_access_log):
    url = "https://example.org/a"
    routes = {"https://example.org/robots.txt": [FakeResponse(200, "")],
              url: [FakeResponse(429, "", {"Retry-After": "7"}), FakeResponse(200, "body")]}
    fetcher, session, clock = make_seq_fetcher(tmp_path, routes)
    resp = fetcher.get(url)
    assert resp.status_code == 200 and resp.text == "body"
    assert session.calls.count(url) == 2
    assert 7 in clock.sleeps
    log = isolated_access_log.read_text(encoding="utf-8")
    assert "HTTP 429" in log and "Retry-After: 7" in log


def test_429_without_header_waits_60(tmp_path):
    url = "https://example.org/a"
    routes = {"https://example.org/robots.txt": [FakeResponse(200, "")],
              url: [FakeResponse(429), FakeResponse(200, "ok")]}
    fetcher, _, clock = make_seq_fetcher(tmp_path, routes)
    assert fetcher.get(url).status_code == 200
    assert 60 in clock.sleeps


def test_429_retry_after_capped_at_300(tmp_path):
    url = "https://example.org/a"
    routes = {"https://example.org/robots.txt": [FakeResponse(200, "")],
              url: [FakeResponse(429, "", {"Retry-After": "3600"}), FakeResponse(200, "ok")]}
    fetcher, _, clock = make_seq_fetcher(tmp_path, routes)
    fetcher.get(url)
    assert 300 in clock.sleeps and 3600 not in clock.sleeps


def test_429_twice_returns_429_uncached_and_logs_both(tmp_path, isolated_access_log):
    url = "https://example.org/a"
    routes = {"https://example.org/robots.txt": [FakeResponse(200, "")], url: [FakeResponse(429)]}
    fetcher, session, _ = make_seq_fetcher(tmp_path, routes)
    resp = fetcher.get(url)
    assert resp.status_code == 429
    assert session.calls.count(url) == 2
    rows = [r for r in isolated_access_log.read_text(encoding="utf-8").splitlines() if "HTTP 429" in r]
    assert len(rows) == 2 and "giving up" in rows[1]
    # Not cached: a second fetcher on the same cache must request again.
    again, again_session, _ = make_seq_fetcher(tmp_path, {url: [FakeResponse(200, "later")]})
    assert again.get(url).text == "later"


def test_retry_after_http_date():
    from datetime import datetime, timezone

    from scoreboard.fetch import retry_after_seconds
    now = datetime(2026, 10, 18, 12, 0, 0, tzinfo=timezone.utc)
    assert retry_after_seconds({"Retry-After": "Sun, 18 Oct 2026 12:00:45 GMT"}, now=now) == 45
    assert retry_after_seconds({"retry-after": "soon"}) == 60
    assert retry_after_seconds({}) == 60


# Only 2xx responses are cached


def test_500_not_cached_and_requested_again(tmp_path):
    url = "https://example.org/a"
    routes = {**ROBOTS_OK, url: FakeResponse(500, "server error")}
    fetcher, session, _ = make_fetcher(tmp_path, routes)
    first = fetcher.get(url)
    assert first.status_code == 500 and not first.from_cache  # final reply after the retries
    calls_after_first = session.calls.count(url)
    assert calls_after_first == 3
    second = fetcher.get(url)
    assert second.status_code == 500 and not second.from_cache
    assert session.calls.count(url) == 2 * calls_after_first  # requested again, not read from cache
    assert not list(tmp_path.glob("*.json")) or all(
        json.loads(p.read_text(encoding="utf-8"))["status_code"] == 200 for p in tmp_path.glob("*.json"))


def test_4xx_not_cached(tmp_path):
    url = "https://example.org/missing"
    routes = {**ROBOTS_OK, url: FakeResponse(404, "not found")}
    fetcher, session, _ = make_fetcher(tmp_path, routes)
    assert fetcher.get(url).status_code == 404
    again, again_session, _ = make_fetcher(tmp_path, {url: FakeResponse(200, "now here")})
    assert again.get(url).text == "now here"
    assert again_session.calls.count(url) == 1


def test_400_invalid_page_not_cached(tmp_path):
    url = "https://example.org/wp-json/wp/v2/posts?page=9"
    routes = {**ROBOTS_OK, url: FakeResponse(400, '{"code": "rest_post_invalid_page_number"}')}
    fetcher, session, _ = make_fetcher(tmp_path, routes)
    fetcher.get(url)
    fetcher.get(url)
    assert session.calls.count(url) == 2


def test_check_robots_status_without_cached_robots(tmp_path):
    routes = {"https://web.archive.org/robots.txt": FakeResponse(404)}
    fetcher, session, _ = make_fetcher(tmp_path, routes)
    assert fetcher.check_robots("https://web.archive.org/web/") == (True, "HTTP 404")
    assert not list(tmp_path.glob("*.json"))


def test_robots_429_counts_as_unreachable(tmp_path):
    routes = {"https://rl.example/robots.txt": FakeResponse(429)}
    fetcher, _, _ = make_fetcher(tmp_path, routes)
    assert fetcher.check_robots("https://rl.example/") == (False, "unreachable")


# Hard request deadline


class HangingSession(FakeSession):
    """Hangs on `url` for the first `hangs` requests (until released), then answers 200."""

    def __init__(self, routes, url, hangs):
        super().__init__(routes)
        import threading
        self.url, self.hangs, self.release = url, hangs, threading.Event()

    def get(self, url, timeout=None):
        if url == self.url:
            self.calls.append(url)
            if self.calls.count(url) <= self.hangs:
                self.release.wait(5)
            return FakeResponse(200, "late body")
        return super().get(url, timeout)


def make_hanging_fetcher(tmp_path, hangs, monkeypatch):
    import scoreboard.fetch as fetch
    monkeypatch.setattr(fetch, "REQUEST_DEADLINE_SECONDS", 0.05)
    clock = FakeClock()
    session = HangingSession(ROBOTS_OK, "https://example.org/slow", hangs)
    fetcher = Fetcher(load_config(), cache_dir=tmp_path, session=session, clock=clock, sleep=clock.sleep)
    return fetcher, session


def test_request_past_deadline_fails_after_retries(tmp_path, monkeypatch):
    from scoreboard.fetch import BACKOFF_SECONDS, MAX_RETRIES
    fetcher, session = make_hanging_fetcher(tmp_path, hangs=99, monkeypatch=monkeypatch)
    assert fetcher.get("https://example.org/slow") is None
    assert fetcher.skip_reason == "request failed"
    assert session.calls.count("https://example.org/slow") == MAX_RETRIES + 1
    assert BACKOFF_SECONDS in fetcher.sleep.__self__.sleeps
    session.release.set()


def test_request_past_deadline_is_retried(tmp_path, monkeypatch):
    fetcher, session = make_hanging_fetcher(tmp_path, hangs=1, monkeypatch=monkeypatch)
    resp = fetcher.get("https://example.org/slow")
    assert resp is not None and resp.text == "late body"
    assert session.calls.count("https://example.org/slow") == 2
    session.release.set()


def test_cancel_sends_no_request(tmp_path):
    routes = {**ROBOTS_OK, "https://example.org/a": FakeResponse(200, "a")}
    fetcher, session, _ = make_fetcher(tmp_path, routes)
    fetcher.cancel = lambda: True
    assert fetcher.get("https://example.org/a") is None
    assert fetcher.skip_reason == "cancelled"
    assert "https://example.org/a" not in session.calls


def test_cancel_never_marks_robots_unreachable(tmp_path):
    routes = {**ROBOTS_OK, "https://example.org/a": FakeResponse(200, "a")}
    fetcher, session, _ = make_fetcher(tmp_path, routes)
    fetcher.cancel = lambda: True
    fetcher.get("https://example.org/a")
    fetcher.cancel = None
    assert fetcher.get("https://example.org/a").text == "a"
