"""Regression checks for live-domain routing and the public content crawl."""
import asyncio
import importlib
import os
import unittest
from unittest.mock import patch

import httpx
from nexwave_mcp import backend

REAL_CLIENT = httpx.AsyncClient


class EnvironmentTests(unittest.TestCase):
    def test_canonical_defaults_and_legacy_aliases(self):
        with patch.dict(os.environ, {}, clear=True):
            importlib.reload(backend)
            self.assertEqual(backend.SITE_URL, "https://trydayclub.com")
            self.assertEqual(backend.API_KEY, "")
        with patch.dict(os.environ, {"NEXWAVE_API_URL": "https://legacy.example/",
                                     "NEXWAVE_API_KEY": "legacy-fixture"}, clear=True):
            importlib.reload(backend)
            self.assertEqual(backend.SITE_URL, "https://legacy.example")
            self.assertEqual(backend.API_KEY, "legacy-fixture")
        with patch.dict(os.environ, {"TDC_API_URL": "https://current.example/",
                                     "TDC_API_KEY": "current-fixture",
                                     "NEXWAVE_API_URL": "https://legacy.example",
                                     "NEXWAVE_API_KEY": "legacy-fixture"}, clear=True):
            importlib.reload(backend)
            self.assertEqual(backend.SITE_URL, "https://current.example")
            self.assertEqual(backend.API_KEY, "current-fixture")
        importlib.reload(backend)


class BackendTests(unittest.IsolatedAsyncioTestCase):
    async def test_quote_uses_current_origin_and_own_insurance_by_default(self):
        seen = []

        def respond(request):
            seen.append(request)
            return httpx.Response(200, json={"ok": True, "plan": request.url.params["plan"]})

        with patch.object(backend, "SITE_URL", "https://trydayclub.com"):
            api = backend.NexwaveAPI()
            api._client = REAL_CLIENT(base_url=backend.SITE_URL,
                                     transport=httpx.MockTransport(respond))
            try:
                result = await api.quote("corolla", "2026-12-01", "2026-12-03")
            finally:
                await api._client.aclose()
        self.assertEqual(str(seen[0].url).split("?")[0], "https://trydayclub.com/api/v1/quote")
        self.assertEqual(result["plan"], "decline")

    async def test_api_errors_preserve_rental_policy_without_exposing_html(self):
        self.assertEqual(backend._error_detail(httpx.Response(409, json={
            "ok": False, "error": "Daily full coverage is pending. Use your own insurance to continue."})),
            "Daily full coverage is pending. Use your own insurance to continue.")
        detail = backend._error_detail(httpx.Response(502, text="<html>private proxy diagnostic</html>"))
        self.assertNotIn("private proxy diagnostic", detail)
        self.assertIn("Try Day Club", detail)

    async def test_full_sitemap_and_concurrent_cold_requests(self):
        site = "https://trydayclub.com"
        urls = [f"{site}/car-rental/area-{i}" for i in range(66)]
        urls += [f"{site}/api/private", f"{site}/checkout", "https://external.example/private"]
        xml = '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + ''.join(
            f"<url><loc>{url}</loc></url>" for url in urls) + '</urlset>'
        active = peak = sitemaps = 0
        seen = []

        async def respond(request):
            nonlocal active, peak, sitemaps
            seen.append(str(request.url))
            if request.url.path == "/sitemap.xml":
                sitemaps += 1
                await asyncio.sleep(0.01)
                return httpx.Response(200, text=xml)
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.005)
            active -= 1
            return httpx.Response(200, headers={"content-type": "text/html"},
                                  text=f"<title>Los Angeles rental {request.url.path}</title>"
                                       "<p>Current rental terms and delivery details for this local area.</p>")

        def client(**kwargs):
            return REAL_CLIENT(transport=httpx.MockTransport(respond), **kwargs)

        index = backend.SiteIndex()

        async def query():
            await index.rebuild()
            return index.search("area-65")

        with patch.object(backend, "SITE_URL", site), patch.object(backend.httpx, "AsyncClient", client):
            first, second = await asyncio.gather(query(), query())
        self.assertTrue(first)
        self.assertEqual(first, second)
        self.assertEqual(len(index._docs), 66)
        self.assertEqual(sitemaps, 1)
        self.assertGreater(peak, 1)
        self.assertLessEqual(peak, backend.CONTENT_CONCURRENCY)
        self.assertEqual(len(seen), 67)
        self.assertIsNotNone(index.fetch(f"{site}/car-rental/area-65"))

    async def test_redirects_cannot_crawl_external_or_private_pages(self):
        site = "https://trydayclub.com"
        urls = [f"{site}/external", f"{site}/private", f"{site}/old", f"{site}/current"]
        xml = '<urlset>' + ''.join(f"<url><loc>{url}</loc></url>" for url in urls) + '</urlset>'
        seen = []

        def respond(request):
            seen.append(str(request.url))
            if request.url.path == "/sitemap.xml":
                return httpx.Response(200, text=xml)
            redirect = {"/external": "https://external.example/secret",
                        "/private": "/checkout/session", "/old": "/current"}.get(request.url.path)
            if redirect:
                return httpx.Response(302, headers={"location": redirect})
            return httpx.Response(200, headers={"content-type": "text/html"},
                                  text="<title>Current terms</title><p>These current rental terms provide public information about rentals.</p>")

        def client(**kwargs):
            return REAL_CLIENT(transport=httpx.MockTransport(respond), **kwargs)

        index = backend.SiteIndex()
        with patch.object(backend, "SITE_URL", site), patch.object(backend.httpx, "AsyncClient", client):
            await index.rebuild()
        self.assertEqual([doc["id"] for doc in index._docs], [f"{site}/current"])
        self.assertNotIn("https://external.example/secret", seen)
        self.assertNotIn(f"{site}/checkout/session", seen)


class PublicToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_quote_schema_and_invocation_default_to_own_insurance(self):
        from fastmcp import Client
        from nexwave_mcp import server

        calls = []

        class FakeAPI:
            async def quote(self, car, start, end, plan):
                calls.append((car, start, end, plan))
                return {"ok": True, "plan": plan, "totalCents": 10000}

        with patch.object(server, "api", lambda: FakeAPI()):
            async with Client(server.build_public_server()) as client:
                tools = {tool.name: tool for tool in await client.list_tools()}
                self.assertEqual(tools["quote_trip"].input_schema["properties"]["plan"]["default"], "decline")
                self.assertIn("without delivery", tools["quote_trip"].description)
                self.assertNotIn("demo", server.PUBLIC_INSTRUCTIONS.lower())
                self.assertNotIn("sketchy", server.PUBLIC_INSTRUCTIONS.lower())
                await client.call_tool("quote_trip", {"car": "corolla", "start": "2026-12-01", "end": "2026-12-03"})
        self.assertEqual(calls, [("corolla", "2026-12-01", "2026-12-03", "decline")])


if __name__ == "__main__":
    unittest.main()
