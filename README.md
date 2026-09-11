<!-- Enki fingerprint -->
# nexwave-mcp-remote — Sketchy Rides as an MCP plugin

**Rent cars with your AI. Manage the fleet with your AI.** Two streamable-HTTP
MCP servers for the [Sketchy Rides](https://sketchyrides.com) LA rental pilot
(Nexwave platform), one Fly.io machine, scale-to-zero.

| Surface | URL | Auth | Who |
|---|---|---|---|
| Renter / public | `https://nexwave-mcp.fly.dev/mcp` | none | anyone's agent |
| Operator | `https://nexwave-mcp.fly.dev/ops/mcp` | OAuth 2.1 login gate | fleet operator |

## Add it to your harness

**Claude Code / Desktop**
```bash
claude mcp add --transport http sketchyrides https://nexwave-mcp.fly.dev/mcp
```

**Codex** (`~/.codex/config.toml`)
```toml
[mcp_servers.sketchyrides]
url = "https://nexwave-mcp.fly.dev/mcp"
```

**ChatGPT** — Settings → Connectors → Developer mode → **+** → paste
`https://nexwave-mcp.fly.dev/mcp`. Deep research works out of the box
(`search` + `fetch` follow the compat schema).

**Cursor** — Settings → MCP → new server → the same URL.

**Operators** use `/ops/mcp` instead — your client will open a sign-in page;
use your operator name + key.

## Tools

**Public** (read-only): `fleet_list` · `availability_check` · `quote_trip`
(live rates, dates, exact checkout math) · `search` / `fetch` (every public
page — fleet, terms, destination guides, blog).

**Ops** (`ops:read`): `ops_overview`, `ops_bookings` · (`ops:write`):
`ops_set_vehicle` — narrow edits: daily rate, delist, description ·
`ops_create_trip` / `ops_modify_trip` / `ops_cancel_trip` — trip lifecycle
(create, adjust dates/vehicle/plan with quote delta, cancel with refund
tier) · `ops_send_comms` — renter emails (booking_confirm |
booking_modified | booking_cancelled; dry-run when no mail provider).

Ops tools call the platform's bearer-gated `/api/v1/ops/*` bridge
([PR #4](https://github.com/Sidarau/nexwave-platform/pull/4)) and degrade
cleanly until it deploys.

## Develop

```bash
uv venv .venv --python 3.12 && uv pip install -p .venv/bin/python .
export NEXWAVE_API_KEY=…   # v1 API key (Vercel env / platform .env.local)
export NEXWAVE_OAUTH_PROFILES='{"alex":{"secret":"…","level":"owner"}}'
.venv/bin/nexwave-mcp --http --port 8378

.venv/bin/python scripts/verify_http.py http://127.0.0.1:8378
.venv/bin/python scripts/verify_oauth.py http://127.0.0.1:8378
# end-to-end trip writes (needs the platform trip/comms bridge deployed):
.venv/bin/python scripts/verify_ops_writes.py http://127.0.0.1:8378
```

stdio mode (local agents that prefer a spawned process): `nexwave-mcp`
with no `--http` serves the public tools.

## Deploy (Fly.io)

```bash
fly apps create nexwave-mcp
fly secrets set NEXWAVE_API_KEY=… NEXWAVE_BASE_URL=https://nexwave-mcp.fly.dev \
  'NEXWAVE_OAUTH_PROFILES={…}'   # generate fresh secrets, never the test ones
fly deploy
```

`min_machines_running = 1` is deliberate: OAuth state is in-memory, and
idle auto-stop would wipe DCR registrations mid-flow.

## Registry (plugin-store discovery)

`server.json` is the official MCP registry manifest. Once the Fly deploy is
live and verified, publish with the registry CLI (`mcp-publisher`, GitHub
auth — the `io.github.sidarau/*` namespace is tied to the GitHub account):

```bash
mcp-publisher publish   # from this repo
```

— Enki · ZEUG-663
