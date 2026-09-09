"""Operator OAuth for nexwave-mcp-remote — adapted from zeug-desk-mcp auth.py.

The ops server (/ops/mcp) is gated by OAuth 2.1 (DCR + PKCE) with a
passphrase login gate. Profiles come from NEXWAVE_OAUTH_PROFILES JSON;
identity — never the client — decides scopes.

Levels
------
owner     ops:read + ops:write          (Alex / platform admins)
ops       ops:read                      (read-only operator)
"""
from __future__ import annotations

import json
import os
from typing import Any

from fastmcp.server.auth.providers.in_memory import InMemoryOAuthProvider
from mcp.server.auth.settings import ClientRegistrationOptions
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse
from starlette.routing import Route


def _scopes_for(profile: dict[str, str]) -> list[str]:
    if profile.get("level") == "owner":
        return ["ops:read", "ops:write"]
    return ["ops:read"]


ALL_SCOPES = ["ops:read", "ops:write"]

LOGIN_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>Sketchy Rides · operator</title><meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{{font-family:ui-sans-serif,system-ui;background:#f6f7f9;color:#101828;
display:grid;place-items:center;height:100vh;margin:0}}
form{{background:#fff;border:1px solid #e4e7ec;border-radius:12px;padding:2rem;width:320px;display:grid;gap:.9rem}}
h1{{font-size:1.05rem;margin:0;font-weight:700;letter-spacing:.02em}}
p{{font-size:.8rem;color:#667085;margin:0}}
input{{background:#fff;border:1.5px solid #d0d5dd;color:#101828;padding:.6rem .7rem;font-size:.9rem;border-radius:8px}}
button{{background:#101828;border:0;border-radius:8px;color:#fff;padding:.7rem;font-weight:600;
letter-spacing:.06em;cursor:pointer}}button:hover{{background:#1570ef}}
.err{{color:#b42318;font-size:.8rem}}</style></head>
<body><form method="post">
<h1>SKETCHY RIDES · FLEET OPS</h1>
<p>{client} is requesting operator access. Sign in with your operator name and key.</p>
{error}
<input type="text" name="name" placeholder="operator name" autocomplete="username" required>
<input type="password" name="passphrase" placeholder="operator key" autocomplete="current-password" required>
{hidden}
<button type="submit">OPEN FLEET OPS</button></form></body></html>"""


class OpsOAuthProvider(InMemoryOAuthProvider):
    """In-memory OAuth 2.1 AS + a passphrase login gate with ops scopes."""

    def __init__(self, base_url: str, profiles: dict[str, dict[str, str]]):
        super().__init__(
            base_url=base_url,
            client_registration_options=ClientRegistrationOptions(
                enabled=True, valid_scopes=None, default_scopes=["ops:read"]),
            required_scopes=["ops:read"],
        )
        self.profiles = profiles

    async def authorize(self, client, params):
        # FastMCP 4.0.3 InMemoryOAuthProvider.authorize drops params.resource
        # (RFC 8707) when building the AuthorizationCode — stamp it back so the
        # exchanged AccessToken carries the resource the client asked for.
        redirect_url = await super().authorize(client, params)
        if getattr(params, "resource", None):
            from urllib.parse import parse_qs, urlparse
            code = parse_qs(urlparse(str(redirect_url)).query).get("code", [None])[0]
            code_obj = self.auth_codes.get(code) if code else None
            if code_obj is not None:
                code_obj.resource = str(params.resource)
        return redirect_url

    async def exchange_authorization_code(self, client, authorization_code):
        # FastMCP 4.0.3 InMemoryOAuthProvider drops authorization_code.resource
        # when building the AccessToken → stored token has resource=None →
        # SDK BearerAuthBackend rejects it (invalid_token). Copy it through to
        # the access token AND the refresh token so refreshes keep the audience.
        token = await super().exchange_authorization_code(client, authorization_code)
        if getattr(authorization_code, "resource", None):
            stored = self.access_tokens.get(token.access_token)
            if stored is not None:
                stored.resource = str(authorization_code.resource)
            if token.refresh_token is not None:
                stored_refresh = self.refresh_tokens.get(token.refresh_token)
                if stored_refresh is not None:
                    stored_refresh.resource = str(authorization_code.resource)  # type: ignore[attr-defined]
        return token

    async def exchange_refresh_token(self, client, refresh_token, scopes):
        token = await super().exchange_refresh_token(client, refresh_token, scopes)
        if getattr(refresh_token, "resource", None):
            stored = self.access_tokens.get(token.access_token)
            if stored is not None:
                stored.resource = str(refresh_token.resource)
            if token.refresh_token is not None:
                stored_refresh = self.refresh_tokens.get(token.refresh_token)
                if stored_refresh is not None:
                    stored_refresh.resource = str(refresh_token.resource)  # type: ignore[attr-defined]
        return token

    def get_routes(self, mcp_path: str | None = None) -> list[Route]:
        routes = super().get_routes(mcp_path)
        return [r for r in routes if not (getattr(r, "path", None) == "/authorize")] + [
            Route("/authorize", self._authorize_get, methods=["GET"]),
            Route("/authorize", self._authorize_post, methods=["POST"]),
        ]

    async def _authorize_get(self, request: Request) -> HTMLResponse:
        return self._page(dict(request.query_params), error="")

    async def _authorize_post(self, request: Request) -> Any:
        form = await request.form()
        q = {k: str(v) for k, v in form.items()
             if k not in ("name", "passphrase", "csrf") and isinstance(v, str)}
        name = str(form.get("name", "")).strip().lower()
        secret = str(form.get("passphrase", ""))
        profile = self.profiles.get(name)

        if not profile or profile["secret"] != secret:
            return self._page(q, error='<span class="err">Unknown operator name or bad key.</span>')

        try:
            client = await self.get_client(str(q["client_id"]))
            if client is None:
                return self._page(q, error='<span class="err">Unregistered client.</span>')
            # In-memory provider filters params.scopes against the client's
            # registered scope string — widen registration so the profile's
            # forced scopes survive.
            forced = _scopes_for(profile)
            client.scope = " ".join(sorted(set((client.scope or "").split()) | set(forced)))
            from mcp.server.auth.provider import AuthorizationParams
            params = AuthorizationParams(
                redirect_uri=str(q["redirect_uri"]),
                redirect_uri_provided_explicitly=True,
                state=q.get("state") or None,
                scopes=forced,  # profile decides — never the client
                code_challenge=str(q["code_challenge"]),
                resource=q.get("resource") or None,
            )
            redirect_url = await self.authorize(client, params)
            return RedirectResponse(redirect_url, status_code=303)
        except Exception as e:  # noqa: BLE001
            return self._page(q, error=f'<span class="err">{type(e).__name__}: {e}</span>')

    def _page(self, q: dict[str, Any], error: str) -> HTMLResponse:
        hidden = "".join(f'<input type="hidden" name="{k}" value="{v}">' for k, v in q.items())
        return HTMLResponse(LOGIN_PAGE.format(
            client=q.get("client_id", "An MCP client"), error=error, hidden=hidden))


def build_ops_auth(base_url: str) -> OpsOAuthProvider:
    profiles_json = os.environ.get("NEXWAVE_OAUTH_PROFILES", "")
    if not profiles_json:
        raise RuntimeError(
            "NEXWAVE_OAUTH_PROFILES required — JSON like "
            '{"alex": {"secret": "…", "level": "owner"}, '
            '"mo": {"secret": "…", "level": "ops"}}')
    profiles = {k.strip().lower(): v for k, v in json.loads(profiles_json).items()}
    for name, p in profiles.items():
        if p.get("level") not in ("owner", "ops"):
            raise RuntimeError(f"profile {name!r}: level must be owner|ops")
        if not p.get("secret"):
            raise RuntimeError(f"profile {name!r}: secret required")
    return OpsOAuthProvider(base_url=base_url, profiles=profiles)
