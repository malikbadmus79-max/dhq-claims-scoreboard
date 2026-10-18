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

import requests

from scoreboard.config import PROJECT_ROOT, load_config

log = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = PROJECT_ROOT / "data_raw" / "cache"
RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_RETRIES = 2
BACKOFF_SECONDS = 10
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
        cached = self._read_cache(f"{origin}/robots.txt")
        return allowed, f"HTTP {cached.status_code}" if cached else "unreachable"

    def _allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            parser = RobotFileParser()
            robots_url = f"{origin}/robots.txt"
            resp = self._read_cache(robots_url) or self._fetch(robots_url)
            if resp is None or resp.status_code >= 500:
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

    def _wait(self, domain: str) -> None:
        last = self._last_request.get(domain)
        if last is not None:
            remaining = self.delay - (self.clock() - last)
            if remaining > 0:
                self.sleep(remaining)
        self._last_request[domain] = self.clock()

    def _fetch(self, url: str) -> Response | None:
        domain = urlsplit(url).netloc
        for attempt in range(MAX_RETRIES + 1):
            if attempt:
                self.sleep(BACKOFF_SECONDS * 2 ** (attempt - 1))
            self._wait(domain)
            try:
                raw = self.session.get(url, timeout=TIMEOUT)
            except requests.RequestException as exc:
                log.warning("request failed (%s): %s", exc.__class__.__name__, url)
                continue
            if raw.status_code in RETRY_STATUSES and attempt < MAX_RETRIES:
                log.warning("status %s, retrying: %s", raw.status_code, url)
                continue
            resp = Response(
                url=url,
                status_code=raw.status_code,
                text=raw.text,
                headers=dict(raw.headers),
            )
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
        data = {
            "url": resp.url,
            "status_code": resp.status_code,
            "headers": resp.headers,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "text": resp.text,
        }
        self._cache_path(resp.url).write_text(json.dumps(data), encoding="utf-8")
