"""Public-server verification over streamable HTTP using a real MCP client
(fastmcp.Client) — never pipe JSON-RPC into stdin; it crashes stdio servers
mid-reply. Hits the LIVE sketchyrides.com API through the server.

  1. /healthz → ok
  2. tools/list → the 5 public tools, and ONLY those
  3. fleet_list → real cars with rates + booking URLs
  4. availability_check → structured answer for a known car
  5. quote_trip → cents total for a known car
  6. search("terms") → {results: [{id, title, url}]} with absolute URLs
  7. fetch(first result) → full text
  8. /ops/mcp without token → 401 (ops is never accidentally public)

Usage:
  NEXWAVE_API_KEY=… .venv/bin/nexwave-mcp --http --port 8379 &
  .venv/bin/python scripts/verify_http.py [base-url]
"""
import asyncio
import json
import sys
import urllib.error
import urllib.request

from fastmcp import Client

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8379").rstrip("/")
failures = 0


def check(label, ok, detail=""):
    global failures
    print(("PASS" if ok else "FAIL"), label, (f"— {detail}" if detail and not ok else ""))
    if not ok:
        failures += 1


def as_json(result):
    if result.structured_content is not None:
        return result.structured_content
    return json.loads(result.content[0].text)


async def main() -> int:
    with urllib.request.urlopen(f"{BASE}/healthz", timeout=10) as r:
        check("healthz", r.read().decode() == "ok")

    with urllib.request.urlopen(f"{BASE}/", timeout=10) as r:
        check("landing page", b"/mcp" in r.read())

    async with Client(f"{BASE}/mcp") as c:
        tools = await c.list_tools()
        names = sorted(t.name for t in tools)
        check("public tools", names == ["availability_check", "fetch", "fleet_list",
                                        "quote_trip", "search"], str(names))

        fleet = as_json(await c.call_tool("fleet_list", {}))
        cars = fleet.get("cars") or fleet.get("fleet") or (fleet if isinstance(fleet, list) else [])
        check("fleet_list returns cars", isinstance(cars, list) and len(cars) > 0,
              json.dumps(fleet)[:200])
        slug = None
        if cars:
            slug = cars[0].get("slug") or cars[0].get("id")

        if slug:
            av = as_json(await c.call_tool("availability_check", {
                "car": slug, "start": "2026-10-01", "end": "2026-10-03"}))
            check("availability_check structured", isinstance(av, dict) and len(av) > 0,
                  json.dumps(av)[:200])

            qt = as_json(await c.call_tool("quote_trip", {
                "car": slug, "start": "2026-10-01", "end": "2026-10-03", "plan": "full"}))
            check("quote_trip has totals", "total" in json.dumps(qt).lower(),
                  json.dumps(qt)[:200])

        s = as_json(await c.call_tool("search", {"query": "rental terms mileage"}))
        results = s.get("results", [])
        check("search returns documents", len(results) > 0, json.dumps(s)[:200])
        if results:
            check("search ids are absolute URLs",
                  all(r["url"].startswith("http") for r in results))
            f = as_json(await c.call_tool("fetch", {"id": results[0]["id"]}))
            check("fetch returns text", len(f.get("text", "")) > 100,
                  f.get("title", ""))

    # ops must never be public
    try:
        req = urllib.request.Request(f"{BASE}/ops/mcp", method="POST",
                                     data=b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}',
                                     headers={"Content-Type": "application/json",
                                              "Accept": "application/json, text/event-stream"})
        urllib.request.urlopen(req, timeout=10)
        check("ops without token → 401", False, "got 200")
    except urllib.error.HTTPError as e:
        check("ops without token → 401", e.code == 401, str(e.code))

    print("\n" + ("ALL PASS" if failures == 0 else f"{failures} FAILURES"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
