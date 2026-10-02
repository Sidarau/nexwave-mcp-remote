"""Backend for Try Day Club — two data sources, both over HTTP.

1. The live v1 REST API at trydayclub.com (bearer-key gated; the SERVER
   holds the key so end users of the public connector need nothing).
2. The public website itself (sitemap-driven) for the ChatGPT deep-research
   compat pair `search`/`fetch` — fleet pages, terms, destination guides,
   and blog posts are picked up automatically as they ship.

No local scripts, no database drivers, no service-role keys — this is what
makes the server deployable anywhere (ZEUG-663).
"""
from __future__ import annotations

import asyncio
import os
import re
import time
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

SITE_URL = (os.environ.get("TDC_API_URL") or os.environ.get("NEXWAVE_API_URL")
            or "https://trydayclub.com").rstrip("/")
API_KEY = os.environ.get("TDC_API_KEY") or os.environ.get("NEXWAVE_API_KEY") or ""
CACHE_TTL = float(os.environ.get("TDC_CONTENT_TTL") or os.environ.get("NEXWAVE_CONTENT_TTL") or 300)
MAX_CONTENT_PAGES = 200
CONTENT_CONCURRENCY = 8
MAX_HTML_CHARS = 400_000
PRIVATE_PATHS = ("/api", "/dashboard", "/trips", "/checkout", "/verify-identity",
                 "/login", "/operator-login", "/set-password")


def _public_url(url: str) -> bool:
    parsed, site = urlsplit(url), urlsplit(SITE_URL)
    return (parsed.scheme == site.scheme and parsed.netloc == site.netloc
            and not parsed.username and not parsed.password
            and not parsed.query and not parsed.fragment
            and not any(parsed.path == path or parsed.path.startswith(path + "/")
                        for path in PRIVATE_PATHS))


class ApiError(RuntimeError):
    def __init__(self, status: int, detail: str):
        super().__init__(f"API {status}: {detail}")
        self.status = status


def _error_detail(response: httpx.Response) -> str:
    """Keep useful API errors without exposing a proxy/server HTML response."""
    try:
        body = response.json()
        error = body.get("error") if isinstance(body, dict) else None
        if isinstance(error, str):
            return error[:300]
    except ValueError:
        pass
    return "Service request failed. Please try again or contact Try Day Club support."


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
            raise ApiError(r.status_code, _error_detail(r))
        return r.json()

    async def fleet(self) -> Any:
        return await self._get("/api/v1/fleet")

    async def availability(self, car: str, start: str, end: str) -> Any:
        return await self._get("/api/v1/availability", {"car": car, "start": start, "end": end})

    async def quote(self, car: str, start: str, end: str, plan: str = "decline") -> Any:
        return await self._get("/api/v1/quote", {"car": car, "start": start, "end": end, "plan": plan})

    # ---- authenticated operator bridge
    async def ops_state(self) -> Any:
        return await self._get("/api/v1/ops/state")

    async def ops_auth_verify(self, email: str, password: str) -> Any:
        """Operator credential check for the MCP login gate (ZEUG-667).
        404 = unavailable bridge → caller uses the compatibility login profiles."""
        r = await self.client().post("/api/v1/ops/auth/verify",
                                     json={"email": email, "password": password})
        if r.status_code != 200:
            raise ApiError(r.status_code, _error_detail(r))
        return r.json()

    async def ops_set_vehicle(self, slug: str, fields: dict[str, Any]) -> Any:
        r = await self.client().post("/api/v1/ops/vehicle", json={"slug": slug, **fields})
        if r.status_code not in (200, 201):
            raise ApiError(r.status_code, _error_detail(r))
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
        self._lock = asyncio.Lock()

    async def _sitemap_urls(self) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=20.0) as c:
                r = await c.get(f"{SITE_URL}/sitemap.xml")
                r.raise_for_status()
            root = ET.fromstring(r.text)
            ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
            urls = [(loc.text or "").strip() for loc in root.findall(".//sm:loc", ns)]
            if not urls:  # sitemap without namespace
                urls = [(loc.text or "").strip() for loc in root.iter("loc")]
            return list(dict.fromkeys(u for u in urls if _public_url(u)))[:MAX_CONTENT_PAGES]
        except Exception:
            return [SITE_URL + "/", SITE_URL + "/terms", SITE_URL + "/blog"]

    async def rebuild(self, force: bool = False) -> None:
        # A second cold request waits for the first crawl instead of seeing an
        # empty cache. Recheck freshness after acquiring the lock.
        async with self._lock:
            if not force and time.time() - self._built_at < CACHE_TTL and self._docs:
                return
            urls = await self._sitemap_urls()
            slots = asyncio.Semaphore(CONTENT_CONCURRENCY)
            async with httpx.AsyncClient(timeout=20.0) as c:
                async def page(url: str) -> dict[str, str] | None:
                    async with slots:
                        try:
                            # Validate each redirect before following it; a
                            # sitemap cannot turn this into an arbitrary fetcher.
                            for _ in range(4):
                                if not _public_url(url):
                                    return None
                                r = await c.get(url)
                                if r.is_redirect:
                                    url = urljoin(str(r.url), r.headers.get("location", ""))
                                    continue
                                break
                            else:
                                return None
                            if r.status_code != 200 or "text/html" not in r.headers.get("content-type", ""):
                                return None
                            html = r.text[:MAX_HTML_CHARS]
                            p = _TextExtractor()
                            p.feed(html)
                            text = p.text()
                            if len(text) < 40:
                                return None
                            final_url = str(r.url)
                            return {
                                "id": final_url,
                                "url": final_url,
                                "title": _extract_title(html) or final_url.rsplit("/", 1)[-1] or "Try Day Club",
                                "text": text[:24_000],
                            }
                        except (httpx.HTTPError, ValueError):
                            return None
                pages = await asyncio.gather(*(page(url) for url in urls))
            # Redirects may converge on one page; keep one canonical document.
            docs = {d["id"]: d for d in pages if d}
            if docs:
                self._docs = list(docs.values())
                self._built_at = time.time()

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
