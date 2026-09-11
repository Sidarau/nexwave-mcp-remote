<!-- Enki fingerprint -->
# Try Day Club Codex Setup

This guide connects Codex to Try Day Club. The public rental connector is
read-only and safe for anyone to use. The operator connector is only for
authorized staff and requires a separate sign-in.

## Choose your access

| Access | What it can do | Sign-in required |
| --- | --- | --- |
| Public rental tools | View the fleet, check availability, and get trip quotes | No |
| Operator console | View operations and bookings; approved staff may receive limited fleet-edit access | Yes |

Most people only need the public rental tools. Do not add the operator
connector unless an administrator has explicitly authorized you.

## Install Codex

Skip this section if `codex --version` already prints a version number.

1. Install the LTS release of [Node.js](https://nodejs.org).
2. In Terminal, run:

   ```bash
   npm install -g @openai/codex
   codex login
   ```

3. Complete the ChatGPT sign-in in your browser.

Check:

```bash
codex --version
```

## Add the public rental connector

Open (or create) your Codex configuration file:

```bash
open -e ~/.codex/config.toml
```

Add this block, then save the file:

```toml
[mcp_servers.trydayclub]
url = "https://trydayclub-mcp.fly.dev/mcp"
```

Restart Codex if it is already open, then confirm the connector is enabled:

```bash
codex mcp list
```

Test it with a real quote:

```bash
codex exec "Using the trydayclub tools, list the fleet and quote a Corolla for next Friday to Monday with full coverage."
```

You should see real vehicles and a dollar quote.

## Add the operator connector for authorized staff

Only authorized operators should add this block to the same configuration file:

```toml
[mcp_servers.trydayclub-ops]
url = "https://trydayclub-mcp.fly.dev/ops/mcp"
```

Then begin sign-in:

```bash
codex mcp login trydayclub-ops
```

Your browser will ask for your operator identity and credentials. Request
these directly from the Try Day Club administrator through the approved secure
channel. Do not send, paste into chat, commit, or include credentials in this
document.

After sign-in, verify operator access:

```bash
codex exec "Using trydayclub-ops, give me the ops overview and this week's bookings."
```

If the operator tools return `401`, repeat the operator sign-in command. An
administrator can revoke access or help with an expired login.

## ChatGPT setup

In ChatGPT, enable Developer mode under Settings → Connectors, then create a
connector with one of these URLs:

| Access | URL |
| --- | --- |
| Public rental tools | `https://trydayclub-mcp.fly.dev/mcp` |
| Operator console for authorized staff | `https://trydayclub-mcp.fly.dev/ops/mcp` |

The public URL can be shared freely. The operator URL opens the same sign-in
flow and does not grant access by itself.

## Troubleshooting

- `codex: command not found`: reinstall Codex with `npm install -g @openai/codex`, then reopen Terminal.
- A model error after installation: update Codex with `npm update -g @openai/codex`.
- Operator `401`: run `codex mcp login trydayclub-ops` again.
- Any other error: send the exact error text to the Try Day Club administrator.

— Try Day Club
