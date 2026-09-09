<!-- Enki fingerprint -->
# HANDOFF — ZEUG-663: nexwave-mcp-remote

**State as of 2026-09-08 ~21:35 PDT.** Loop-driven completion. If you are a
resuming agent: read this file, do exactly the "Remaining" steps in order,
update this file + Linear ZEUG-663 at every stopping point.

## What exists (working, verified)

`~/Documents/WORK/ZEUG/SAAS/nexwave-mcp-remote/` — FastMCP 4.0.3, Python 3.12,
uv venv at `.venv/` (regular install — `uv pip install -p .venv/bin/python .`
after ANY src edit; the editable .pth is broken under uv here).

- `/mcp` — public renter MCP, zero auth: fleet_list, availability_check,
  quote_trip (proxy live `https://sketchyrides.com/api/v1/*` with server-held
  NEXWAVE_API_KEY), search + fetch (ChatGPT deep-research compat, sitemap-driven
  site index, auto-picks-up /blog as posts ship).
- `/ops/mcp` — operator MCP, OAuth 2.1 login gate (NEXWAVE_OAUTH_PROFILES):
  ops_overview, ops_bookings (ops:read), ops_set_vehicle (ops:write).
  Ops tools call `/api/v1/ops/*` on the platform — that bridge does NOT exist
  yet; they degrade with a clear "bridge not deployed" message (by design).
- `/` marketing/install landing page, `/healthz`.
- Dockerfile + fly.toml (app `nexwave-mcp`, sjc, 512MB shared, min 1 machine).

**Verified locally:** `scripts/verify_http.py` ALL 10 PASS against live
sketchyrides.com. `scripts/verify_oauth.py` all pass EXCEPT token use.

## THE BUG — FIXED (2026-09-08 ~23:20 PDT, cron tick 1 + main session)

Three fixes landed, all verified:
1. `auth.py` — FastMCP 4.0.3 InMemoryOAuthProvider drops RFC 8707 `resource`
   at three hops (authorize → exchange_code → exchange_refresh); all three
   overridden to copy it through. Also `_authorize_post` now calls
   `self.authorize` (was bypassing the override via `super()`).
2. `server.py` — the route-merged Starlette app dropped the ops sub-app's
   auth middleware → route-level RequireAuthMiddleware 401'd every token.
   Fix: pass `ops_app.user_middleware` to the outer Starlette. Public routes
   unaffected (no RequireAuth wrapper → unauthenticated passes through).

**Local verification: BOTH suites ALL PASS** (verify_http 10/10 against live
sketchyrides.com, verify_oauth 11/11 incl. scope-filtered tools/list).

## Remaining (in order)

1. ~~Fix + local green~~ ✅ DONE.
2. **Deploy to Fly — BLOCKED ON HUMAN: Fly auth.** The NoxKey
   `zeuglab/fly/FLY_API_TOKEN` is STALE (Fly API 401 on whoami) and
   ~/.fly/config.yml holds no working token. Alex must run
   `flyctl auth login` (interactive browser) in a terminal, or mint a fresh
   token (fly.io → account → tokens) and `noxkey set zeuglab/fly/FLY_API_TOKEN`.
   Once `flyctl auth whoami` succeeds, do NOT ask again — proceed:
   `fly apps create nexwave-mcp` (tolerate "already exists"), then
   `fly secrets set NEXWAVE_API_KEY=<same key> NEXWAVE_BASE_URL=https://nexwave-mcp.fly.dev 'NEXWAVE_OAUTH_PROFILES=<GENERATE fresh strong secrets — NOT the test ones>'`,
   then `fly deploy`. NEVER print secret values to logs.
   Store the operator profiles JSON in NoxKey: `noxkey set zeuglab/nexwave/MCP_OAUTH_PROFILES`.
3. **Verify live.** Both verify scripts against `https://nexwave-mcp.fly.dev`
   (set VERIFY_OWNER_PASS/VERIFY_OPS_PASS to the real profile secrets).
   Also curl the landing page.
4. ~~Ops bridge PR~~ ✅ DONE: https://github.com/Sidarau/nexwave-platform/pull/4
   (branch enki/v1-ops-bridge, clean worktree off origin/main; typecheck exit 0,
   web suite 153/153 incl. 4 new). NOT merged — Codex/Alex merges.
   MCP repo pushed: https://github.com/Sidarau/nexwave-mcp-remote
5. **README + closeout.** README install kit ✅ done in repo. Remaining:
   comment ZEUG-663 with live evidence (verify outputs, fly URL, PR link),
   move to In Review. Kill the cron loop on completion.

## Hard rules for the loop

- Never print NEXWAVE_API_KEY or OAuth secrets (values) anywhere.
- Never merge PRs, never touch DNS, never edit the dirty nexwave-platform tree.
- Max 3 fix attempts on the same failing verifier → stop, comment ZEUG-663
  Blocked with the exact error, and end the run.
- fly deploy is reversible (fly apps destroy nexwave-mcp) — allowed.
- Completion = verify scripts ALL PASS against https://nexwave-mcp.fly.dev
  + ops bridge PR open + ZEUG-663 updated. Then remove this cron job.
