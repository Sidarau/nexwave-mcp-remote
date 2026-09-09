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

## What is NOT done (out of scope, by design)

- PR #4 merge (human gate).
- NoxKey Touch ID / `STRIPE_*` planting on sketchyrides.com (Nexwave human lane,
  separate workstream).
- Disabled cron `nexwave-verification-stack-research` (41cd9858f87f) left as-is.
