<!-- Enki fingerprint -->
# Sketchy Rides — AI operator access (Kostik)

You can now talk to the Sketchy Rides platform from ChatGPT or Codex: check the
fleet, see bookings, quote trips. Trip create/edit/cancel + renter messaging is
the next build (ZEUG-666).

## Your login

- Operator name: `kostik`
- Key: Alex sends it to you separately (never in the same message as this link).

## ChatGPT (phone or desktop)

1. Settings → Connectors → enable **Developer mode** (Advanced settings).
2. Connectors → **+** (New connector).
3. Paste URL: `https://nexwave-mcp.fly.dev/ops/mcp` → Create.
4. It opens a sign-in page → enter `kostik` + your key.
5. In any chat: "Using sketchyrides, show this week's bookings."

## Codex (laptop)

Already in the shared config. One-time:

```bash
codex mcp login sketchyrides-ops   # opens sign-in; kostik + your key
```

Then in any Codex session: "list the fleet on sketchyrides", "quote a Corolla
Fri–Mon with full coverage".

## Public tier (no login)

`https://nexwave-mcp.fly.dev/mcp` — read-only fleet/availability/quote +
site search. Safe to give to anyone's agent.

— Enki · ZEUG-663
