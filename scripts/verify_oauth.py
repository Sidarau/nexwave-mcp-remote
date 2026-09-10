"""End-to-end OAuth verification for the OPS server (/ops/mcp) — the exact
dance a client performs, adapted from zme-mcp scripts/verify_oauth.py.

  1. protected-resource + authorization-server metadata discovery
  2. dynamic client registration (DCR)
  3. GET /authorize          → login form
  4. POST /authorize         → bad key rejected (no code leak), good key → code
  5. POST /token (PKCE S256) → access token carries the profile's scopes
  6. MCP initialize with token → 200 ; without token → 401
  7. ops-profile token lists tools → read tools only (all five write tools
     hidden); owner token lists tools → every ops tool present

Usage:
  NEXWAVE_OAUTH_PROFILES='{"alex":{"secret":"s3cret","level":"owner"},
  "ops":{"secret":"viewonly","level":"ops"}}' \
    .venv/bin/nexwave-mcp --http --port 8378 &
  .venv/bin/python scripts/verify_oauth.py [base-url]
"""
import base64
import hashlib
import json
import os
import secrets
import sys
import urllib.parse

import httpx

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8378").rstrip("/")
OWNER_PASS = os.environ.get("VERIFY_OWNER_PASS", "s3cret")
OPS_PASS = os.environ.get("VERIFY_OPS_PASS", "viewonly")
WRITE_TOOLS = ["ops_set_vehicle", "ops_create_trip", "ops_modify_trip",
               "ops_cancel_trip", "ops_send_comms"]
failures = 0


def check(label, ok, detail=""):
    global failures
    print(("PASS" if ok else "FAIL"), label, (f"— {detail}" if detail and not ok else ""))
    if not ok:
        failures += 1


def oauth_dance(client: httpx.Client, name: str, passphrase: str) -> tuple[str, list[str]]:
    meta = client.get(f"{BASE}/.well-known/oauth-authorization-server").json()
    assert meta["registration_endpoint"].startswith(BASE), meta

    reg = client.post(meta["registration_endpoint"], json={
        "client_name": "verify-oauth",
        "redirect_uris": ["http://localhost:9999/callback"],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "scope": "ops:read ops:write",
    })
    assert reg.status_code in (200, 201), reg.text
    cid = reg.json()["client_id"]

    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    q = {"response_type": "code", "client_id": cid,
         "redirect_uri": "http://localhost:9999/callback",
         "code_challenge": challenge, "code_challenge_method": "S256",
         "state": "xyz", "scope": "ops:read ops:write",
         "resource": f"{BASE}/ops/mcp"}
    form_page = client.get(f"{BASE}/authorize", params=q)
    assert "passphrase" in form_page.text, form_page.text[:200]

    bad = client.post(f"{BASE}/authorize", data={**q, "name": name,
                                                 "passphrase": "wrong"},
                      follow_redirects=False)
    assert bad.status_code == 200 and "bad key" in bad.text, bad.status_code
    assert "code=" not in bad.text

    good = client.post(f"{BASE}/authorize", data={**q, "name": name,
                                                  "passphrase": passphrase},
                       follow_redirects=False)
    assert good.status_code == 303, (good.status_code, good.text[:300])
    loc = good.headers["location"]
    code = urllib.parse.parse_qs(urllib.parse.urlparse(loc).query)["code"][0]

    tok = client.post(meta["token_endpoint"], data={
        "grant_type": "authorization_code", "code": code,
        "redirect_uri": "http://localhost:9999/callback",
        "client_id": cid, "code_verifier": verifier,
    })
    assert tok.status_code == 200, tok.text
    body = tok.json()
    return body["access_token"], body.get("scope", "").split()


def mcp_call(client, token, method, params=None, sid=None):
    headers = {"Content-Type": "application/json",
               "Accept": "application/json, text/event-stream"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if sid:
        headers["mcp-session-id"] = sid
    return client.post(f"{BASE}/ops/mcp", headers=headers, json={
        "jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}), headers


def parse_body(r):
    if r.headers.get("content-type", "").startswith("application/json"):
        return r.json()
    line = [l for l in r.text.splitlines() if l.startswith("data:")][0]
    return json.loads(line[5:])


def session(client, token):
    h = {"Content-Type": "application/json",
         "Accept": "application/json, text/event-stream",
         "Authorization": f"Bearer {token}"}
    init = client.post(f"{BASE}/ops/mcp", headers=h, json={
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                   "clientInfo": {"name": "verify", "version": "0"}}})
    sid = init.headers.get("mcp-session-id")
    client.post(f"{BASE}/ops/mcp", headers={**h, "mcp-session-id": sid}, json={
        "jsonrpc": "2.0", "method": "notifications/initialized"})
    return {**h, "mcp-session-id": sid}


def main() -> int:
    with httpx.Client(timeout=30) as client:
        prm = client.get(f"{BASE}/.well-known/oauth-protected-resource/ops/mcp")
        check("protected-resource metadata (path-appended)", prm.status_code == 200)
        asm = client.get(f"{BASE}/.well-known/oauth-authorization-server")
        check("authorization-server metadata", asm.status_code == 200)

        owner_token, owner_scopes = oauth_dance(client, "alex", OWNER_PASS)
        check("owner dance", bool(owner_token))
        check("owner scopes include write", "ops:write" in owner_scopes, str(owner_scopes))
        ops_token, ops_scopes = oauth_dance(client, "ops", OPS_PASS)
        check("ops dance", bool(ops_token))
        check("ops profile is read-only", ops_scopes == ["ops:read"], str(ops_scopes))

        r, _ = mcp_call(client, owner_token, "initialize", {
            "protocolVersion": "2025-03-26", "capabilities": {},
            "clientInfo": {"name": "verify", "version": "0"}})
        check("ops MCP with token", r.status_code == 200, r.text[:120])
        r, _ = mcp_call(client, None, "initialize", {
            "protocolVersion": "2025-03-26", "capabilities": {},
            "clientInfo": {"name": "verify", "version": "0"}})
        check("ops MCP without token → 401", r.status_code == 401, str(r.status_code))

        # scope enforcement: read-only profile must not see the write tools
        sh = session(client, ops_token)
        lst = client.post(f"{BASE}/ops/mcp", headers=sh, json={
            "jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        names = [t["name"] for t in parse_body(lst).get("result", {}).get("tools", [])]
        check("ops profile sees read tools",
              "ops_overview" in names and "ops_bookings" in names, str(names))
        check("ops profile does NOT see write tools",
              all(t not in names for t in WRITE_TOOLS), str(names))

        sh = session(client, owner_token)
        lst = client.post(f"{BASE}/ops/mcp", headers=sh, json={
            "jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        names = [t["name"] for t in parse_body(lst).get("result", {}).get("tools", [])]
        check("owner sees all ops tools",
              all(t in names for t in
                  ["ops_overview", "ops_bookings", *WRITE_TOOLS]), str(names))

    print("\n" + ("ALL PASS" if failures == 0 else f"{failures} FAILURES"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
