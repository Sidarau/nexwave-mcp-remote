"""Try Day Club (trydayclub.com) as MCP servers (ZEUG-663).

Brand and production booking website: Try Day Club (trydayclub.com).

Two servers, one process, one Fly.io machine:

  /mcp      PUBLIC renter surface — zero auth. Any agent (Codex, Claude,
            ChatGPT, Cursor, Hermes) adds one connector and can list the
            fleet, check availability, quote a trip, and search/fetch every
            public page (fleet, terms, guides, blog).

  /ops/mcp  OPERATOR surface — OAuth 2.1 login gate.
            Fleet/booking overview and narrow fleet writes, proxied through
            the platform's bearer-gated /api/v1/ops/* bridge.

stdio mode (trydayclub-mcp with no --http) serves the public tools only, for
local agent configs that prefer a spawned process.

Env:
  TDC_API_KEY             v1 API bearer key (NEXWAVE_API_KEY compatibility alias)
  TDC_API_URL             defaults to https://trydayclub.com (NEXWAVE_API_URL alias)
  TDC_BASE_URL            external URL of THIS server (NEXWAVE_BASE_URL alias)
  TDC_OAUTH_PROFILES      compatibility login profiles (NEXWAVE_OAUTH_PROFILES alias)
"""
from __future__ import annotations

import json
import os
from typing import Any

from fastmcp import FastMCP
from fastmcp.server.auth import require_scopes
from mcp.types import Icon, ToolAnnotations

from .backend import ApiError, api, site_index

WEBSITE_URL = "https://trydayclub.com"
BRAND_ICONS = [Icon(src=f"{WEBSITE_URL}/app-icon.svg",
                    mimeType="image/svg+xml", sizes=["any"])]

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False,
                            idempotent_hint=True, open_world_hint=True)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False,
                        idempotent_hint=False, open_world_hint=True)

PUBLIC_INSTRUCTIONS = """\
Try Day Club is a live Los Angeles car-rental company (trydayclub.com).
Use fleet_list for current cars, rates and booking URLs, and
availability_check before discussing available dates. Dates use a 10am
Los Angeles pickup and return time. quote_trip estimates Playa Vista
pickup with eligible renter-provided insurance (plan=decline); daily full
coverage is currently pending. Quote amounts are USD cents and exclude
optional delivery, addons and promotions. Confirm the final total and
chosen times on the booking website; availability can change before payment.
Use search/fetch for rental terms, local rental and delivery pages, guides
and blog posts, and cite their URLs. Delivery is limited to the website's
supported areas and requires an exact-address check before payment.
These tools read information; complete the reservation on trydayclub.com."""

OPS_INSTRUCTIONS = """\
Try Day Club operator console for AI agents. ops_overview gives fleet +
booking state, ops_bookings lists trips, ops_set_vehicle applies narrow
fleet edits (rate, hidden, description). Reads first; confirm with
the human before any write."""


def build_public_server() -> FastMCP:
    mcp = FastMCP(name="trydayclub", instructions=PUBLIC_INSTRUCTIONS,
                  website_url=WEBSITE_URL, icons=BRAND_ICONS)

    @mcp.tool(annotations=READ_ONLY)
    async def fleet_list() -> dict[str, Any]:
        """List the current published Try Day Club LA fleet: daily rates,
        mileage terms, photos, and booking URLs."""
        return await api().fleet()

    @mcp.tool(annotations=READ_ONLY)
    async def availability_check(car: str, start: str, end: str) -> dict[str, Any]:
        """Check a date window with 10am Los Angeles pickup and return times.
        The booking website confirms chosen times and current availability.

        car: car slug or 17-char VIN · start/end: YYYY-MM-DD (end = return day)
        """
        return await api().availability(car, start, end)

    @mcp.tool(annotations=READ_ONLY)
    async def quote_trip(car: str, start: str, end: str, plan: str = "decline") -> dict[str, Any]:
        """Estimate rental and tax in USD cents for Playa Vista pickup at
        10am Los Angeles time on both dates, without delivery, addons or
        promotions. plan=decline uses eligible renter-provided insurance;
        full coverage is pending and liability is unsupported. The website
        confirms insurance eligibility, chosen times and the final total."""
        return await api().quote(car, start, end, plan)

    @mcp.tool(annotations=READ_ONLY)
    async def search(query: str) -> dict[str, Any]:
        """Search the public Try Day Club site — rental terms, fleet pages,
        destination guides, blog posts. Returns {results: [{id, title, url}]};
        call fetch(id) for the full page text."""
        idx = site_index()
        await idx.rebuild()
        return {"results": idx.search(query)}

    @mcp.tool(annotations=READ_ONLY)
    async def fetch(id: str) -> dict[str, Any]:
        """Fetch the full text of one site page by its id (a URL from search)."""
        idx = site_index()
        await idx.rebuild()
        d = idx.fetch(id)
        if not d:
            return {"id": id, "title": "", "text": "", "url": "",
                    "metadata": {"error": "not found — run search first"}}
        return {"id": d["id"], "title": d["title"], "text": d["text"],
                "url": d["url"], "metadata": {"source": "trydayclub.com"}}

    return mcp


def build_ops_server(base_url: str) -> FastMCP:
    from .auth import build_ops_auth

    provider = build_ops_auth(base_url)
    mcp = FastMCP(name="trydayclub-ops", instructions=OPS_INSTRUCTIONS, auth=provider,
                  website_url=WEBSITE_URL, icons=BRAND_ICONS)

    def _err(e: Exception) -> str:
        if isinstance(e, ApiError) and e.status == 404:
            return "The operator service is unavailable (404). Contact Try Day Club support."
        if isinstance(e, ApiError):
            return f"The operator service returned HTTP {e.status}. Contact Try Day Club support."
        return "The operator service could not be reached. Please try again."

    @mcp.tool(annotations=READ_ONLY, auth=[require_scopes("ops:read")])
    async def ops_overview() -> Any:
        """Operator snapshot: fleet (with hidden cars), addons, delivery
        settings, bookings, expenses — the same state the ops dashboard shows."""
        try:
            return await api().ops_state()
        except Exception as e:  # noqa: BLE001
            return _err(e)

    @mcp.tool(annotations=READ_ONLY, auth=[require_scopes("ops:read")])
    async def ops_bookings(status: str = "") -> Any:
        """List bookings, optionally filtered by status
        (pending_payment | confirmed | checked_out | completed | cancelled)."""
        try:
            state = await api().ops_state()
            bookings = state.get("bookings", []) if isinstance(state, dict) else []
            if status:
                bookings = [b for b in bookings if b.get("status") == status]
            return {"count": len(bookings), "bookings": bookings}
        except Exception as e:  # noqa: BLE001
            return _err(e)

    @mcp.tool(annotations=WRITE, auth=[require_scopes("ops:write")])
    async def ops_set_vehicle(slug: str, daily_rate_cents: int = 0,
                              hidden: bool | None = None,
                              description: str = "") -> Any:
        """Narrow fleet edit. Pass only the fields to change:
        daily_rate_cents (>0), hidden (true = delist), description.
        Confirm with the operator before calling — this changes the live site."""
        fields: dict[str, Any] = {}
        if daily_rate_cents > 0:
            fields["dailyRateCents"] = daily_rate_cents
        if hidden is not None:
            fields["hidden"] = hidden
        if description:
            fields["description"] = description
        if not fields:
            return "Nothing to change — pass at least one field."
        try:
            return await api().ops_set_vehicle(slug, fields)
        except Exception as e:  # noqa: BLE001
            return _err(e)

    return mcp


LANDING = """<!doctype html><html><head><meta charset="utf-8">
<title>Try Day Club · MCP</title>
<link rel="icon" href="https://trydayclub.com/app-icon.svg" type="image/svg+xml"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{font-family:ui-sans-serif,system-ui;background:#f6f7f9;color:#101828;margin:0;padding:3rem 1.25rem}
main{max-width:640px;margin:0 auto}h1{font-size:1.4rem;margin:0 0 .25rem}
p,li{font-size:.9rem;color:#475467;line-height:1.55}code,pre{background:#eef2f6;border-radius:6px;font-size:.82rem}
code{padding:.1rem .35rem}pre{padding:.8rem 1rem;overflow:auto;border:1px solid #e4e7ec}
h2{font-size:.95rem;margin:2rem 0 .4rem}.tag{display:inline-block;background:#1570ef;color:#fff;
border-radius:999px;padding:.15rem .6rem;font-size:.7rem;font-weight:600;letter-spacing:.05em}</style></head>
<body><main>
<a href="https://trydayclub.com" aria-label="Try Day Club home"><img src="https://trydayclub.com/app-icon.svg" alt="Try Day Club" width="72" height="72"></a><br>
<span class="tag">MCP · AI-NATIVE RENTAL</span>
<h1>Try Day Club for agents</h1>
<p>Add one connector and your AI can shop the LA fleet, quote a trip, and read
every page of the site. Operators get a second, sign-in-gated connector that
manages the fleet.</p>
<h2>Renters &amp; agents — public connector (no sign-in)</h2>
<pre>URL: {base}/mcp</pre>
<p><b>Claude:</b> <code>claude mcp add --transport http trydayclub {base}/mcp</code><br>
<b>Codex:</b> <code>[mcp_servers.trydayclub] url = "{base}/mcp"</code><br>
<b>ChatGPT:</b> Add this URL as a custom MCP connector in your client; search and fetch are built in</p>
<h2>Operators — fleet management (OAuth sign-in)</h2>
<pre>URL: {base}/ops/mcp</pre>
<p>Same steps; your client opens a sign-in page. Use your authorized operator email and password.</p>
<h2>Tools</h2>
<p><b>Public:</b> fleet_list · availability_check · quote_trip · search · fetch<br>
<b>Ops:</b> ops_overview · ops_bookings · ops_set_vehicle</p>
<p>Fleet &amp; booking: <a href="https://trydayclub.com">trydayclub.com</a></p>
</main></body></html>"""


def http_app(base_url: str):
    from contextlib import AsyncExitStack, asynccontextmanager

    from starlette.applications import Starlette
    from starlette.responses import HTMLResponse, PlainTextResponse
    from starlette.routing import Route

    public = build_public_server()
    ops = build_ops_server(base_url)

    public_app = public.http_app(path="/mcp")
    ops_app = ops.http_app(path="/ops/mcp")

    @asynccontextmanager
    async def lifespan(app):
        # Both FastMCP apps run their session managers in lifespan — merging
        # routes into one Starlette app must not drop that.
        async with AsyncExitStack() as stack:
            await stack.enter_async_context(public_app.router.lifespan_context(public_app))
            await stack.enter_async_context(ops_app.router.lifespan_context(ops_app))
            yield

    async def healthz(request):
        return PlainTextResponse("ok")

    async def landing(request):
        return HTMLResponse(LANDING.replace("{base}", base_url))

    routes = [
        Route("/", landing, methods=["GET"]),
        Route("/healthz", healthz, methods=["GET"]),
        *public_app.routes,
        *ops_app.routes,
    ]
    # The ops sub-app's middleware (AuthenticationMiddleware + BearerAuthBackend,
    # AuthContextMiddleware, RequestContextMiddleware) populates scope["user"]
    # and the token context — the /ops/mcp route's RequireAuthMiddleware 401s
    # without it. Public routes are unaffected: no Authorization header →
    # unauthenticated scope → passes through (no RequireAuth wrapper there).
    middleware = list(getattr(ops_app, "user_middleware", []))
    return Starlette(routes=routes, middleware=middleware, lifespan=lifespan)


def main() -> None:
    import argparse

    p = argparse.ArgumentParser(prog="trydayclub-mcp",
                                description="Try Day Club MCP servers")
    p.add_argument("--http", action="store_true")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=int(os.environ.get("PORT") or 8000))
    args = p.parse_args()

    if args.http:
        import uvicorn
        base_url = (os.environ.get("TDC_BASE_URL") or os.environ.get("NEXWAVE_BASE_URL")
                    or f"http://{args.host}:{args.port}").rstrip("/")
        uvicorn.run(http_app(base_url), host=args.host, port=args.port, log_level="info")
    else:
        build_public_server().run()


if __name__ == "__main__":
    main()
