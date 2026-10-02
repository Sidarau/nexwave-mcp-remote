# Try Day Club MCP connector

Two streamable HTTP MCP servers for [Try Day Club](https://trydayclub.com),
a live Los Angeles car rental company. The public connector reads current
fleet, availability, pickup estimates and website content. The separate
operator connector requires sign-in and can update limited fleet fields.

| Surface | URL | Access |
| --- | --- | --- |
| Public rental tools | `https://trydayclub-mcp.fly.dev/mcp` | No sign-in |
| Operator console | `https://trydayclub-mcp.fly.dev/ops/mcp` | Authorized operator sign-in |

## Connect

For Claude:

```bash
claude mcp add --transport http trydayclub https://trydayclub-mcp.fly.dev/mcp
```

For Codex, add to `~/.codex/config.toml`:

```toml
[mcp_servers.trydayclub]
url = "https://trydayclub-mcp.fly.dev/mcp"
```

Other MCP clients can use the same public URL. Custom connector access in
ChatGPT depends on the account's developer access; see the
[setup guide](docs/CODEX-SETUP-SHAREABLE.md).

Authorized operators use `/ops/mcp` and sign in with their operator email
and password. Credentials must come through the approved secure channel.

## Rental tools and limits

`fleet_list` returns the published fleet, rates, photos and booking URLs.
`availability_check` checks a date window using 10am Los Angeles pickup and
return times. `quote_trip` returns USD cents for Playa Vista pickup using
eligible renter-provided insurance (`plan=decline`). Daily full coverage is
pending and liability-only coverage is unsupported. Quotes exclude optional
delivery, addons and promotions. The booking website confirms insurance
eligibility, chosen times and the final total; availability may change
before payment.

`search` and `fetch` read the official site's public sitemap, including
local rental pages, delivery areas, terms and guides. The cache refreshes
lazily every five minutes with up to 200 pages and eight concurrent requests.
Private routes and external redirects are excluded. Delivery areas require
an exact-address check on the website before payment.

Operator read tools are `ops_overview` and `ops_bookings` (`ops:read`).
`ops_set_vehicle` (`ops:write`) edits rate, visibility or description and
requires the operator's confirmation before use.

## Develop and verify

```bash
uv venv .venv --python 3.12
uv pip install -p .venv/bin/python .
.venv/bin/trydayclub-mcp --http --port 8378
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/verify_http.py http://127.0.0.1:8378
.venv/bin/python scripts/verify_oauth.py http://127.0.0.1:8378
```

Provide the API bearer key and operator compatibility profiles through the
approved secret injection mechanism before starting the HTTP server. Never
copy production credentials into documentation or command arguments.

| Setting | Purpose |
| --- | --- |
| `TDC_API_URL` | Production API/site origin; defaults to `https://trydayclub.com` |
| `TDC_API_KEY` | API bearer key held by the server |
| `TDC_BASE_URL` | This connector's external URL, used by OAuth |
| `TDC_OAUTH_PROFILES` | Operator compatibility profiles JSON |
| `TDC_CONTENT_TTL` | Content cache lifetime in seconds; defaults to 300 |

The corresponding `NEXWAVE_*` environment names remain compatibility aliases
for deployed integrations. The existing Python module, distribution name,
repository identity and `nexwave-mcp` command remain compatible;
`trydayclub-mcp` is the canonical command. Stdio mode (no `--http`) serves
only public rental tools.

## Deploy and discovery

The existing Fly application is `trydayclub-mcp`:

```bash
fly deploy -a trydayclub-mcp
```

Exactly one machine stays running because OAuth registrations and tokens
live in memory. Restarting the process requires clients to sign in again.
Verify public tools and operator authorization after deploying.

`server.json` describes the public endpoint for the MCP registry. Registry
publication and public ChatGPT directory publication are separate processes;
a working connector alone does not establish directory acceptance or
proactive recommendations. The public plugin review package lives in
`plugin/`.

Both MCP surfaces advertise `https://trydayclub.com` and its official red
app mark at `https://trydayclub.com/app-icon.svg`. Clients may cache metadata;
refresh the existing connector after deployment.
