"""Polite HTTP fetcher: robots.txt check, per-domain delay, on-disk cache, retries."""

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from email.utils import parsedate_to_datetime

import requests

from scoreboard.access_log import log_access
from scoreboard.config import PROJECT_ROOT, load_config

log = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = PROJECT_ROOT / "data_raw" / "cache"
RETRY_STATUSES = {500, 502, 503, 504}
MAX_RETRIES = 2
BACKOFF_SECONDS = 10
# HTTP 429: wait for Retry-After (capped), or RATE_LIMIT_WAIT without one, then retry once.
RATE_LIMIT_WAIT = 60
RETRY_AFTER_CAP = 300
TIMEOUT = (10, 30)
OFFLINE_MISS = "offline: not in cache"


@dataclass
class Response:
    url: str
    status_code: int
    text: str
    headers: dict = field(default_factory=dict)
    from_cache: bool = False

    def json(self):
        return json.loads(self.text)


def full_url(url: str, params: dict | None = None) -> str:
    """Return the URL with query parameters encoded, as requests would send it."""
    return requests.Request("GET", url, params=params).prepare().url


def _header(headers: dict, name: str) -> str:
    return next((v for k, v in headers.items() if k.lower() == name), "")


def retry_after_seconds(headers: dict, now: datetime | None = None) -> float:
    """Seconds to wait after HTTP 429: Retry-After as seconds or an HTTP date, capped at
    RETRY_AFTER_CAP; RATE_LIMIT_WAIT when the header is absent or unreadable."""
    value = _header(headers, "retry-after").strip()
    if not value:
        return RATE_LIMIT_WAIT
    try:
        seconds = float(value)
    except ValueError:
        try:
            when = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return RATE_LIMIT_WAIT
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        seconds = (when - (now or datetime.now(timezone.utc))).total_seconds()
    return min(max(seconds, 0.0), RETRY_AFTER_CAP)


def cache_key(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


class Fetcher:
    def __init__(
        self,
        config: dict | None = None,
        cache_dir: Path | str = DEFAULT_CACHE_DIR,
        session=None,
        clock=time.monotonic,
        sleep=time.sleep,
        offline: bool = False,
    ):
        config = config or load_config()
        self.user_agent = config["user_agent"]
        self.delay = float(config["min_delay_seconds"])
        self.domain_delays = {d.lower(): float(s) for d, s in (config.get("domain_delay_seconds") or {}).items()}
        self.obey_robots = bool(config["obey_robots_txt"])
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": self.user_agent})
        self.clock = clock
        self.sleep = sleep
        self._last_request: dict[str, float] = {}
        self._robots: dict[str, RobotFileParser] = {}
        self._robots_unreachable: set[str] = set()
        self._robots_status: dict[str, int] = {}
        self.skip_reason: str | None = None
        self.offline = offline

    def get(self, url: str, params: dict | None = None) -> Response | None:
        """Fetch a URL, or return None if robots.txt disallows it or the request fails."""
        url = full_url(url, params)
        self.skip_reason = None
        cached = self._read_cache(url)
        if cached is not None:
            return cached
        if self.offline:
            self.skip_reason = OFFLINE_MISS
            return None
        if self.obey_robots and not self._allowed(url):
            origin = "{0.scheme}://{0.netloc}".format(urlsplit(url))
            if origin in self._robots_unreachable:
                self.skip_reason = "robots.txt unreachable"
            else:
                self.skip_reason = "robots.txt disallows"
            log.warning("%s; skipped %s", self.skip_reason, url)
            return None
        resp = self._fetch(url)
        if resp is None:
            self.skip_reason = "request failed"
        return resp

    def check_robots(self, url: str) -> tuple[bool, str]:
        """Whether robots.txt allows `url` for the configured user agent, and how robots.txt
        answered: "HTTP <status>" or "unreachable"."""
        allowed = self._allowed(url)
        origin = "{0.scheme}://{0.netloc}".format(urlsplit(url))
        if origin in self._robots_unreachable:
            return allowed, "unreachable"
        status = self._robots_status.get(origin)
        return allowed, f"HTTP {status}" if status else "unreachable"

    def _allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            parser = RobotFileParser()
            robots_url = f"{origin}/robots.txt"
            resp = self._read_cache(robots_url) or self._fetch(robots_url)
            if resp is not None:
                self._robots_status[origin] = resp.status_code
            # A rate-limit reply says nothing about the rules, so it counts as unreachable.
            if resp is None or resp.status_code >= 500 or resp.status_code == 429:
                parser.disallow_all = True
                self._robots_unreachable.add(origin)
            elif resp.status_code in (401, 403):
                parser.disallow_all = True
            elif resp.status_code >= 400:
                parser.allow_all = True
            else:
                parser.parse(resp.text.splitlines())
            self._robots[origin] = parser
        return self._robots[origin].can_fetch(self.user_agent, url)

    def delay_for(self, domain: str) -> float:
        """The configured delay for a domain (www. ignored), else min_delay_seconds."""
        host = domain.lower().split(":")[0].removeprefix("www.")
        return self.domain_delays.get(host, self.delay)

    def _wait(self, domain: str) -> None:
        last = self._last_request.get(domain)
        if last is not None:
            remaining = self.delay_for(domain) - (self.clock() - last)
            if remaining > 0:
                self.sleep(remaining)
        self._last_request[domain] = self.clock()

    def _fetch(self, url: str) -> Response | None:
        domain = urlsplit(url).netloc
        rate_limited_once = False
        attempt = 0
        while attempt <= MAX_RETRIES:
            if attempt:
                self.sleep(BACKOFF_SECONDS * 2 ** (attempt - 1))
            self._wait(domain)
            try:
                raw = self.session.get(url, timeout=TIMEOUT)
            except requests.RequestException as exc:
                log.warning("request failed (%s): %s", exc.__class__.__name__, url)
                attempt += 1
                continue
            resp = Response(url=url, status_code=raw.status_code, text=raw.text, headers=dict(raw.headers))
            if raw.status_code == 429:
                wait = retry_after_seconds(resp.headers)
                action = "giving up" if rate_limited_once else f"waiting {wait:.0f} s, then one retry"
                log_access(domain, url, "HTTP 429", f"Rate limited (Retry-After: "
                           f"{_header(resp.headers, 'retry-after') or 'none'}); {action}")
                log.warning("HTTP 429, %s: %s", action, url)
                if rate_limited_once:
                    # A rate-limit reply is not content: returned, never cached.
                    return resp
                rate_limited_once = True
                self.sleep(wait)
                continue
            if raw.status_code in RETRY_STATUSES and attempt < MAX_RETRIES:
                log.warning("status %s, retrying: %s", raw.status_code, url)
                attempt += 1
                continue
            self._write_cache(resp)
            return resp
        log.error("giving up after %d retries: %s", MAX_RETRIES, url)
        return None

    def forget(self, url: str) -> bool:
        """Remove a cached response, e.g. a bot-challenge page that is not content."""
        path = self._cache_path(url)
        if path.exists():
            path.unlink()
            return True
        return False

    def _cache_path(self, url: str) -> Path:
        return self.cache_dir / f"{cache_key(url)}.json"

    def _read_cache(self, url: str) -> Response | None:
        path = self._cache_path(url)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return Response(
            url=data["url"],
            status_code=data["status_code"],
            text=data["text"],
            headers=data["headers"],
            from_cache=True,
        )

    def _write_cache(self, resp: Response) -> None:
        """Only 2xx responses are cached. A 4xx or 5xx reply is requested again next time, so a
        transient error or refusal is never replayed from the cache."""
        if not 200 <= resp.status_code < 300:
            return
        data = {
            "url": resp.url,
            "status_code": resp.status_code,
            "headers": resp.headers,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "text": resp.text,
        }
        self._cache_path(resp.url).write_text(json.dumps(data), encoding="utf-8")
