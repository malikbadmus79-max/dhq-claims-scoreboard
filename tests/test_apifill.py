import json

from scoreboard.apifill import (
    content_text,
    fill_from_api,
    normalise_link,
    purge_challenge_pages,
    slug_candidates,
)
from scoreboard.fetch import Response

PARAGRAPH = (
    "The Defence Headquarters said troops neutralised terrorists and arrested suspects in the "
    "North East during the week under review, while recovering weapons and ammunition. "
)


def test_slug_candidates():
    assert slug_candidates("https://gazettengr.com/troops-killed-105-terrorists/") == ["troops-killed-105-terrorists"]
    assert slug_candidates(
        "https://www.premiumtimesng.com/news/top-news/656485-military-kills-43-terrorists-dhq.html"
    ) == ["656485-military-kills-43-terrorists-dhq", "military-kills-43-terrorists-dhq"]


def test_normalise_link_ignores_scheme_www_and_trailing_slash():
    assert normalise_link("https://www.premiumtimesng.com/a/b.html") == normalise_link("http://premiumtimesng.com/a/b.html/")


def test_content_text_from_rendered_html():
    html = f"<p>{PARAGRAPH * 4}</p><script>var x = 1;</script><p>{PARAGRAPH * 4}</p>"
    text = content_text(html)
    assert "Defence Headquarters" in text and "var x" not in text


class SlugFetcher:
    skip_reason = None

    def __init__(self, posts_by_slug):
        self.posts_by_slug = posts_by_slug
        self.requests = []

    def get(self, url, params=None):
        self.requests.append(params)
        posts = self.posts_by_slug.get(params["slug"], [])
        return Response(url, 200, json.dumps(posts))


def test_fill_requires_matching_link():
    url = "https://www.premiumtimesng.com/news/top-news/656485-military-kills-43-dhq.html"
    content = {"rendered": f"<p>{PARAGRAPH * 6}</p>"}
    wrong = SlugFetcher({"656485-military-kills-43-dhq": [{"link": "https://www.premiumtimesng.com/other.html", "content": content}]})
    assert fill_from_api(wrong, "premiumtimesng.com", url) == ("no matching post", "")

    right = SlugFetcher({"military-kills-43-dhq": [{"link": url, "content": content}]})
    status, text = fill_from_api(right, "premiumtimesng.com", url)
    assert status == "ok" and "Defence Headquarters" in text
    assert all(p["_fields"] == "link,content" for p in right.requests)


def test_purge_removes_only_challenge_pages(tmp_path):
    challenge = {"url": "u1", "status_code": 200, "headers": {}, "text": "<html><script>slowAES.decrypt()</script></html>"}
    article = {"url": "u2", "status_code": 200, "headers": {}, "text": f"<html><p>{PARAGRAPH}</p></html>"}
    (tmp_path / "a.json").write_text(json.dumps(challenge), encoding="utf-8")
    (tmp_path / "b.json").write_text(json.dumps(article), encoding="utf-8")
    assert purge_challenge_pages(tmp_path) == 1
    assert [p.name for p in tmp_path.glob("*.json")] == ["b.json"]
