"""End-to-end OPS WRITE verification for /ops/mcp (ZEUG-666).

Runs the full trip lifecycle through the MCP tools against the platform
bridge: create → visible in state → modify → comms → cancel, plus the
scope gate (ops read-only profile must be rejected on write tools).

REQUIRES the platform /api/v1/ops/* trip+comms endpoints to be deployed —
against a bridge without them the create step fails with the friendly
"bridge not deployed yet" string and every later check cascades to FAIL.

Usage:
  NEXWAVE_OAUTH_PROFILES='{"alex":{"secret":"s3cret","level":"owner"},
  "ops":{"secret":"viewonly","level":"ops"}}' \
    .venv/bin/nexwave-mcp --http --port 8378 &
  .venv/bin/python scripts/verify_ops_writes.py [base-url]

Env:
  VERIFY_OWNER_PASS    owner passphrase (default s3cret)
  VERIFY_OPS_PASS      ops passphrase (default viewonly)
  VERIFY_VEHICLE_SLUG  fleet slug to book (default: first non-hidden
                       vehicle from ops_overview)
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
VEHICLE_SLUG = os.environ.get("VERIFY_VEHICLE_SLUG", "")
WRITE_TOOLS = ["ops_set_vehicle", "ops_create_trip", "ops_modify_trip",
               "ops_cancel_trip", "ops_send_comms"]
START, END, END2 = "2027-03-10", "2027-03-13", "2027-03-14"
RENTER = "MCP Verify"
failures = 0


def check(label, ok, detail=""):
    global failures
    print(("PASS" if ok else "FAIL"), label, (f"— {detail}" if detail and not ok else ""))
    if not ok:
        failures += 1


def oauth_dance(client: httpx.Client, name: str, passphrase: str) -> str:
    """Same dance as verify_oauth.py (minus the bad-key probe): metadata →
    DCR → authorize → token (PKCE S256). Returns the access token."""
    meta = client.get(f"{BASE}/.well-known/oauth-authorization-server").json()
    reg = client.post(meta["registration_endpoint"], json={
        "client_name": "verify-ops-writes",
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
    return tok.json()["access_token"]


def session(client, token):
    h = {"Content-Type": "application/json",
         "Accept": "application/json, text/event-stream",
         "Authorization": f"Bearer {token}"}
    init = client.post(f"{BASE}/ops/mcp", headers=h, json={
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                   "clientInfo": {"name": "verify-writes", "version": "0"}}})
    sid = init.headers.get("mcp-session-id")
    client.post(f"{BASE}/ops/mcp", headers={**h, "mcp-session-id": sid}, json={
        "jsonrpc": "2.0", "method": "notifications/initialized"})
    return {**h, "mcp-session-id": sid}


def parse_body(r):
    if r.headers.get("content-type", "").startswith("application/json"):
        return r.json()
    line = [l for l in r.text.splitlines() if l.startswith("data:")][0]
    return json.loads(line[5:])


def call_tool(client, headers, name, arguments):
    """tools/call → (http response, payload). payload is structuredContent
    when present, else JSON-parsed text content, else the raw text."""
    r = client.post(f"{BASE}/ops/mcp", headers=headers, json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": name, "arguments": arguments}})
    if r.status_code != 200:
        return r, {"_http_error": f"{r.status_code}: {r.text[:200]}"}
    body = parse_body(r)
    if "error" in body:
        return r, {"_rpc_error": str(body["error"])[:200]}
    result = body.get("result", {})
    if result.get("isError"):
        texts = " ".join(c.get("text", "") for c in result.get("content", []))
        return r, {"_tool_error": texts[:200]}
    if "structuredContent" in result:
        return r, result["structuredContent"]
    text = "".join(c.get("text", "") for c in result.get("content", []))
    try:
        return r, json.loads(text)
    except (ValueError, TypeError):
        return r, text


def tool_names(client, headers):
    r = client.post(f"{BASE}/ops/mcp", headers=headers, json={
        "jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    return [t["name"] for t in parse_body(r).get("result", {}).get("tools", [])]


def pick_vehicle(state) -> str:
    vehicles = (state.get("vehicles") or state.get("fleet") or []) if isinstance(state, dict) else []
    for v in vehicles:
        if isinstance(v, dict) and v.get("slug") and not v.get("hidden"):
            return v["slug"]
    return ""


def booking_ref(b) -> str:
    return (b or {}).get("ref") or (b or {}).get("id") or ""


def main() -> int:
    global failures
    with httpx.Client(timeout=30) as client:
        owner = oauth_dance(client, "alex", OWNER_PASS)
        ops = oauth_dance(client, "ops", OPS_PASS)
        check("oauth dances (owner + ops)", bool(owner) and bool(ops))
        oh, oph = session(client, owner), session(client, ops)

        # 0. pick a bookable vehicle
        slug = VEHICLE_SLUG
        if not slug:
            _, state = call_tool(client, oh, "ops_overview", {})
            slug = pick_vehicle(state)
        check("vehicle slug available", bool(slug), "no slug from VERIFY_VEHICLE_SLUG/ops_overview")

        # 1. create
        _, created = call_tool(client, oh, "ops_create_trip", {
            "vehicle_slug": slug, "start_date": START, "end_date": END,
            "plan": "full", "renter_name": RENTER,
            "renter_email": "mcp-verify@example.com"})
        ok = isinstance(created, dict) and created.get("ok")
        booking = created.get("booking", {}) if ok else {}
        ref = booking_ref(booking)
        quote = created.get("quote", {}) if ok else {}
        old_total = quote.get("totalCents")
        check("ops_create_trip returns booking + quote",
              ok and bool(ref) and isinstance(old_total, int),
              str(created)[:200])

        # 2. visible in state
        _, state = call_tool(client, oh, "ops_overview", {})
        bookings = state.get("bookings", []) if isinstance(state, dict) else []
        check("new booking appears in ops state",
              any(booking_ref(b) == ref for b in bookings), f"ref={ref!r}")

        # 3. modify end_date +1 day → quote delta consistent
        _, mod = call_tool(client, oh, "ops_modify_trip",
                           {"booking_id": ref, "end_date": END2})
        ok = isinstance(mod, dict) and mod.get("ok")
        delta = mod.get("quoteDeltaCents") if ok else None
        new_total = (mod.get("quote") or {}).get("totalCents") if ok else None
        check("ops_modify_trip quoteDeltaCents == new − old",
              ok and isinstance(delta, int) and isinstance(new_total, int)
              and isinstance(old_total, int) and delta == new_total - old_total,
              str(mod)[:200])

        # 4. comms booking_confirm → rendered addresses the renter
        _, comms = call_tool(client, oh, "ops_send_comms",
                             {"booking_id": ref, "template": "booking_confirm"})
        rendered = comms.get("rendered", {}) if isinstance(comms, dict) else {}
        blob = f"{rendered.get('subject', '')} {rendered.get('text', '')}"
        check("ops_send_comms renders renter name (dry-run ok)",
              isinstance(comms, dict) and comms.get("ok")
              and comms.get("mode") in ("sent", "dry-run", "failed")
              and RENTER in blob, str(comms)[:200])

        # 5. cancel → far-future pickup ⇒ full refund
        _, cancel = call_tool(client, oh, "ops_cancel_trip", {"booking_id": ref})
        ok = isinstance(cancel, dict) and cancel.get("ok")
        check("ops_cancel_trip → full refund + cancelled",
              ok and (cancel.get("refund") or {}).get("tier") == "full"
              and (cancel.get("booking") or {}).get("status") == "cancelled",
              str(cancel)[:200])

        # 6. read-only ops profile: write tools hidden AND calls rejected
        names = tool_names(client, oph)
        check("ops profile tools/list hides write tools",
              all(t not in names for t in WRITE_TOOLS), str(names))
        r, res = call_tool(client, oph, "ops_create_trip", {
            "vehicle_slug": slug, "start_date": START, "end_date": END,
            "plan": "full", "renter_name": RENTER,
            "renter_email": "mcp-verify@example.com"})
        rejected = (r.status_code == 403 or "_http_error" in str(res)
                    or "_rpc_error" in str(res) or "_tool_error" in str(res))
        check("ops profile tools/call ops_create_trip rejected",
              rejected and not (isinstance(res, dict) and res.get("ok")),
              f"status={r.status_code} body={str(res)[:150]}")

    print("\n" + ("ALL PASS" if failures == 0 else f"{failures} FAILURES"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
