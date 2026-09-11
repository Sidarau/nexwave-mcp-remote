<!-- Enki fingerprint -->
# Try Day Club in Codex — setup for Alex & Kostik

10 minutes. Do every step in order. When a step has a ✓ check, don't move on
until it passes.

---

## Part 1 — Kostik only: install Codex (skip if already installed)

1. Install Node.js from https://nodejs.org (the LTS button).
2. Open Terminal and run:

   ```bash
   npm install -g @openai/codex
   ```

3. Sign in:

   ```bash
   codex login
   ```

   A browser opens — sign in with your ChatGPT account.

✓ Check: `codex --version` prints a version number.

---

## Part 2 — both: connect the Try Day Club plugin

4. Open (or create) the config file:

   ```bash
   open -e ~/.codex/config.toml
   ```

5. Paste this block at the bottom, save, close:

   ```toml
   # Try Day Club — public fleet/quote tools (no sign-in)
   [mcp_servers.trydayclub]
   url = "https://nexwave-mcp.fly.dev/mcp"

   # Try Day Club — operator console (sign-in)
   [mcp_servers.trydayclub-ops]
   url = "https://nexwave-mcp.fly.dev/ops/mcp"
   ```

✓ Check: `codex mcp list` shows `trydayclub` and `trydayclub-ops`, both `enabled`.

---

## Part 3 — both: sign in to the operator console

6. Run:

   ```bash
   codex mcp login trydayclub-ops
   ```

7. A browser page opens asking for your operator name and key:

   | Who | Operator name | Key |
   |---|---|---|
   | Alex | `alex` | in NoxKey: `zeuglab/nexwave/MCP_OAUTH_PROFILES` |
   | Kostik | `kostik` | Alex sends it to you (one message, nothing else in it) |

8. Submit. The page says success; the terminal confirms login.

✓ Check: `codex mcp list` now shows `trydayclub-ops` as `OAuth` (logged in).

---

## Part 4 — both: test it

9. Run:

   ```bash
   codex exec "Using the trydayclub tools, list the fleet and quote a Corolla for next Friday to Monday with full coverage."
   ```

✓ Check: the answer names real cars (Genesis G70, BMW 330i, …) and a dollar
quote. If it does, you're live.

10. Operator test (after step 8):

    ```bash
    codex exec "Using trydayclub-ops, give me the ops overview and this week's bookings."
    ```

---

## If something breaks

- **`codex: command not found`** → redo Part 1, then close and reopen Terminal.
- **Model error mentioning `gpt-6-astra`** (Alex's machine) → the installed
  Codex CLI is too old for the pinned model: `npm update -g @openai/codex`,
  or add `-m gpt-5.5` to any `codex exec` command.
- **Login page rejects the key** → check for a trailing space when pasting;
  keys start with `nwk_`.
- **`trydayclub-ops` tools return 401** → redo Part 3; the login expired.
- **Anything else** → send Alex the exact red text.

---

## Bonus: same plugin in ChatGPT (phone works)

1. ChatGPT → Settings → Connectors → enable **Developer mode**.
2. Connectors → **+** → URL: `https://nexwave-mcp.fly.dev/ops/mcp` → Create.
3. Sign in with the same operator name + key when the page opens.
4. New chat → "Using Try Day Club, show this week's bookings."

The public version (no sign-in, read-only) is
`https://nexwave-mcp.fly.dev/mcp` — safe to give to anyone.

— Enki · ZEUG-663
