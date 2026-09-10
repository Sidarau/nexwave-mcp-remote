<!-- Enki fingerprint -->
# HANDOFF — ZEUG-663: nexwave-mcp-remote

**State: CLOSED ✅ (2026-09-09 ~01:15 PDT, cron tick).** All acceptance criteria met.
This loop is done — completion cron job `dd40e3d2a460` removed. No further action.

## Final verified state

- **Remote MCP live:** https://nexwave-mcp.fly.dev (app `nexwave-mcp`, Fly.io sjc).
  Landing + `/healthz` 200. OAuth secrets on Fly match NoxKey
  `zeuglab/nexwave/MCP_OAUTH_PROFILES`.
- **`scripts/verify_http.py https://nexwave-mcp.fly.dev` → ALL PASS (10/10)**.
- **`scripts/verify_oauth.py https://nexwave-mcp.fly.dev` → ALL PASS (11/11)**
  (owner + ops dances, scope-filtered tools/list, 401 without token).
- **Ops bridge PR:** https://github.com/Sidarau/nexwave-platform/pull/4
  (`enki/v1-ops-bridge`, clean worktree, typecheck 0, web 153/153). OPEN,
  MERGEABLE — NOT merged. Codex/Alex merges.
- **MCP repo:** https://github.com/Sidarau/nexwave-mcp-remote @ `58222a4`
  (fly.toml now caps `max_machines_running = 1` — OAuth DCR/authorize/exchange
  must hit the same process; committed + pushed, matches deployed config).
- **Linear ZEUG-663:** closeout evidence comment posted
  (`703358ec-7feb-4016-bdcc-dccb5b6040d5`), state → **In Review**.

## Gotchas learned this tick (worth remembering)

- **beartype claw cold import ~96s** on first `import fastmcp.server.server`
  (triggered inside `fastmcp.Client(...)` transport inference) on a fresh/macOS-
  indexed venv; warm cache → 1.8s. If a verify run "hangs" right after a fresh
  venv, warm the import once before concluding failure.
- Deploy had already happened (Alex's main session) despite local `flyctl auth
  whoami` still failing — check `curl https://nexwave-mcp.fly.dev/healthz`
  before assuming the Fly-auth blocker still holds.
- 2026-09-10: `verify_http.py` (fastmcp `Client`) hung >4min with zero output
  against the LIVE URL while `verify_oauth.py` (httpx) passed 11/11 in seconds
  and Codex's rmcp client served real `fleet_list` calls — i.e. a client-side
  fastmcp/beartype stall, not a server fault. If the live URL answers
  /healthz + OAuth, suspect the local fastmcp import before suspecting Fly.

## What is NOT done (out of scope, by design)

- PR #4 merge (human gate).
- NoxKey Touch ID / `STRIPE_*` planting on sketchyrides.com (Nexwave human lane,
  separate workstream).
- Disabled cron `nexwave-verification-stack-research` (41cd9858f87f) left as-is.

## ZEUG-666 — ops trip writes + renter comms (MCP side)

- Four new owner-tier (`ops:write`) tools on `/ops/mcp`: `ops_create_trip`,
  `ops_modify_trip`, `ops_cancel_trip`, `ops_send_comms` — backed by new
  `NexwaveAPI.ops_create_trip / ops_modify_trip / ops_cancel_trip /
  ops_send_comms` methods against the platform bridge (`POST/PATCH
  /api/v1/ops/trips*`, `POST /api/v1/ops/comms`).
- **Bridge endpoints 404 until the ZEUG-666 platform PR deploys** — tools
  return the friendly "bridge not deployed yet" string, same as the
  ZEUG-663 reads did pre-merge.
- Verify locally: run the server with test profiles, then
  `scripts/verify_http.py` (public, unchanged) and `scripts/verify_oauth.py`
  (scope checks now cover all five write tools).
- Full lifecycle check once the platform bridge is live:
  `.venv/bin/python scripts/verify_ops_writes.py <base-url>` — creates a
  2027-03 trip ("MCP Verify"), asserts state visibility, quote-delta math
  on modify, comms rendering (dry-run ok), full-refund cancel, and that the
  read-only ops profile is rejected on write calls.
