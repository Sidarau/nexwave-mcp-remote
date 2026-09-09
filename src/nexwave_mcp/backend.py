"""Backend for nexwave-mcp-remote — two data sources, both over HTTP.

1. The live v1 REST API at sketchyrides.com (bearer-key gated; the SERVER
   holds the key so end users of the public connector need nothing).
2. The public website itself (sitemap-driven) for the ChatGPT deep-research
   compat pair `search`/`fetch` — fleet pages, terms, destination guides,
   and blog posts are picked up automatically as they ship.

No local scripts, no database drivers, no service-role keys — this is what
makes the server deployable anywhere (ZEUG-663).
"""
from __future__ import annotations

import os
import re
import time
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from typing import Any

import httpx

SITE_URL = (os.environ.get("NEXWAVE_API_URL") or "https://sketchyrides.com").rstrip("/")
API_KEY = os.environ.get("NEXWAVE_API_KEY") or ""
CACHE_TTL = float(os.environ.get("NEXWAVE_CONTENT_TTL") or 300)
MAX_CONTENT_PAGES = 60


class ApiError(RuntimeError):
    def __init__(self, status: int, detail: str):
        super().__init__(f"API {status}: {detail}")
        self.status = status


class NexwaveAPI:
    """Thin async client over the live v1 REST API."""

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=SITE_URL,
                headers={"Authorization": f"Bearer {API_KEY}"} if API_KEY else {},
                timeout=20.0,
            )
        return self._client

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        r = await self.client().get(path, params={k: v for k, v in (params or {}).items() if v is not None})
        if r.status_code != 200:
            raise ApiError(r.status_code, r.text[:300])
        return r.json()

    async def fleet(self) -> Any:
        return await self._get("/api/v1/fleet")

    async def availability(self, car: str, start: str, end: str) -> Any:
        return await self._get("/api/v1/availability", {"car": car, "start": start, "end": end})

    async def quote(self, car: str, start: str, end: str, plan: str = "full") -> Any:
        return await self._get("/api/v1/quote", {"car": car, "start": start, "end": end, "plan": plan})

    # ---- operator bridge (ships with the platform PR; absent → ApiError 404)
    async def ops_state(self) -> Any:
        return await self._get("/api/v1/ops/state")

    async def ops_set_vehicle(self, slug: str, fields: dict[str, Any]) -> Any:
        r = await self.client().post("/api/v1/ops/vehicle", json={"slug": slug, **fields})
        if r.status_code not in (200, 201):
            raise ApiError(r.status_code, r.text[:300])
        return r.json()


# --------------------------------------------------------------------------
# Site content index for the ChatGPT search/fetch compat pair.

class _TextExtractor(HTMLParser):
    """Minimal HTML → text. Skips script/style/noscript, keeps block breaks."""

    SKIP = {"script", "style", "noscript", "svg", "head"}

    def __init__(self) -> None:
        super().__init__()
        self._skip = 0
        self.parts: list[str] = []
        self.title = ""

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in self.SKIP:
            self._skip += 1
        if tag in ("p", "div", "br", "li", "h1", "h2", "h3", "h4", "tr", "section", "article"):
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)

    def text(self) -> str:
        raw = "".join(self.parts)
        raw = re.sub(r"[ \t]+", " ", raw)
        raw = re.sub(r"\n\s*\n+", "\n\n", raw)
        return raw.strip()


def _extract_title(html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S | re.I)
    return re.sub(r"<[^>]+>|\s+", " ", m.group(1)).strip() if m else ""


class SiteIndex:
    """Sitemap-driven content cache. Rebuilt lazily every CACHE_TTL seconds."""

    def __init__(self) -> None:
        self._docs: list[dict[str, str]] = []
        self._built_at = 0.0
        self._lock = False

    async def _sitemap_urls(self) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=20.0) as c:
                r = await c.get(f"{SITE_URL}/sitemap.xml")
                r.raise_for_status()
            root = ET.fromstring(r.text)
            ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
            urls = [loc.text or "" for loc in root.findall(".//sm:loc", ns)]
            if not urls:  # sitemap without namespace
                urls = [loc.text or "" for loc in root.iter("loc")]
            return [u for u in urls if u.startswith("http")][:MAX_CONTENT_PAGES]
        except Exception:
            return [SITE_URL + "/", SITE_URL + "/terms", SITE_URL + "/blog"]

    async def rebuild(self, force: bool = False) -> None:
        if self._lock or (not force and time.time() - self._built_at < CACHE_TTL and self._docs):
            return
        self._lock = True
        try:
            urls = await self._sitemap_urls()
            docs: list[dict[str, str]] = []
            async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as c:
                for url in urls:
                    try:
                        r = await c.get(url)
                        if r.status_code != 200 or "text/html" not in r.headers.get("content-type", ""):
                            continue
                        p = _TextExtractor()
                        p.feed(r.text[:400_000])
                        text = p.text()
                        if len(text) < 40:
                            continue
                        docs.append({
                            "id": url,
                            "url": url,
                            "title": _extract_title(r.text) or url.rsplit("/", 1)[-1] or "Sketchy Rides",
                            "text": text[:24_000],
                        })
                    except Exception:
                        continue
            if docs:
                self._docs = docs
                self._built_at = time.time()
        finally:
            self._lock = False

    def search(self, query: str, limit: int = 10) -> list[dict[str, str]]:
        terms = [t for t in re.findall(r"[a-z0-9]+", query.lower()) if len(t) > 1]
        if not terms:
            return []
        scored = []
        for d in self._docs:
            title = d["title"].lower()
            body = d["text"].lower()
            score = sum(3 * title.count(t) + body.count(t) for t in terms)
            if score > 0:
                scored.append((score, d))
        scored.sort(key=lambda x: -x[0])
        # Documents, not chunks — ids are page URLs, one hit per page by construction.
        return [{"id": d["id"], "title": d["title"], "url": d["url"]} for _, d in scored[:limit]]

    def fetch(self, doc_id: str) -> dict[str, str] | None:
        for d in self._docs:
            if d["id"] == doc_id:
                return d
        return None


_api: NexwaveAPI | None = None
_index: SiteIndex | None = None


def api() -> NexwaveAPI:
    global _api
    if _api is None:
        _api = NexwaveAPI()
    return _api


def site_index() -> SiteIndex:
    global _index
    if _index is None:
        _index = SiteIndex()
    return _index
