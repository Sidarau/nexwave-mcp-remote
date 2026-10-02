# Try Day Club public plugin preparation

This is a portable Agent Plugins 1.0.0 package for the public renter connection. The upload ZIP includes exactly `plugin.json`, `mcp.json`, and the unmodified official `assets/tdc-icon.svg`. No skills, local executables, credentials, or private connections are bundled. Local review notes and validators stay outside the ZIP.

The public listing describes the existing rental service, with own eligible insurance required and optional full coverage pending availability. Browsing, availability checks, quotes, and public guides are available through the connection; booking and payment happen on Try Day Club's website.

## Validate and build

Run `uv run --no-project --with jsonschema python plugin/validate_package.py --check-urls --build` from the repository root. This supplies Python's `jsonschema` dependency without changing the project's dependencies. If your Python already includes that package, `python3 plugin/validate_package.py --check-urls --build` also works. The validator uses the downloaded canonical Agent Plugins JSON Schemas plus deterministic checks for OpenAI's documented submission constraints. It verifies the official square SVG, listing URLs, lengths, contrast, starter prompts, case counts, single public connection, and ZIP allowlist. A passing local validation does not establish platform approval or conversational test success.

The output is `plugin/dist/trydayclub-1.0.0.zip`; validation evidence is in `plugin/validation/package-checks.json`. Rebuild after editing package metadata or review cases.

## Listing and support

The package name is `trydayclub`, matching the current public server namespace; the display name is Try Day Club. No assigned dashboard plugin ID is fabricated. Use the existing dashboard plugin when uploading an update, preserving its identity. If an existing release has a different portable name or version, obtain its release ZIP and reconcile those values before upload.

`supportURL` points to the real homepage, `https://trydayclub.com`. Select the persistent **Contact us** control or **Contact the team** button to reach the team's call/text options. This was discovered on the live site; `/contact` is not a published page. A dedicated support page can replace this value if the owner publishes one.

The icon is an exact download of `https://trydayclub.com/app-icon.svg`, a 1024-square red-and-white TDC mark. The `#E32636` brand color comes from that SVG. Category **Travel** is listed among the supported categories in the official submission-errors reference.

## Review evidence still required

The manifest contains exactly five positive and three negative cases with expected tool names and observable results. These are review specifications, not claims that ChatGPT executed them. See `validation/review-evidence.json` for their current status. Run every case against the updated public endpoint in a fresh ChatGPT connection, capture actual results, and record any failures. Use future dates and a real published car; no guaranteed inventory, quote total, or insurance approval is hardcoded. Repeat after a relevant endpoint change.

A reviewer-accessible video walkthrough of the cases and functionality is required for MCP review. Its URL is deliberately omitted until a real recording exists. Supply it in `extensions.com.openai.review.demo_recording_url`, or in the editable review details if the dashboard allows it, then validate and rebuild as applicable. Never substitute a nonexistent URL. The public connection requires no sign-in, so reviewer credentials are not needed for its browsing tools. Do not place credentials or reviewer instructions in the ZIP.

## Owner and dashboard steps

1. Select the intended OpenAI organization/project. The submitter must be an organization owner or have **Apps Management Write**. Complete individual or business verification in organization settings and select the verified publishing identity corresponding to this brand. This package does not establish ownership or verification.
2. At [Plugins](https://platform.openai.com/plugins), upload to the existing plugin if one is already registered. Otherwise create a new draft. Check the selected version and identity; a local name does not publish or assign a platform ID.
3. Under **Metadata & Skills**, inspect and resolve validation findings. Under **MCPs**, connect the one endpoint, `https://trydayclub-mcp.fly.dev/mcp`, with no authentication. Complete the portal's domain-verification challenge and automated tool scan.
4. Host the exact portal-provided challenge token as plain text at the portal's precise HTTPS challenge origin plus `/.well-known/openai-apps-challenge`. The origin must be the MCP hostname or an eligible parent domain. Return only the token. Do not guess a token or replace a different plugin's token. The website's domain alone does not prove ownership of the Fly endpoint. Contact support if no eligible origin is controllable.
5. Confirm all five positive and three negative cases have been observed on the submitted endpoint, provide the accessible walkthrough recording, review release notes and commerce disclosure, and resolve required setup errors. Check desktop and mobile behavior before submission.
6. The owner completes required policy attestations and submits the selected draft for review. One review can be active per plugin. After approval, the owner chooses **Publish plugin**; approval does not publish automatically.

For an existing plugin, the current update flow does not support changing the connected MCP URL; contact support if its registered URL differs. Hosted tool changes can be rescanned independently. Metadata and asset updates require a new ZIP. No upload, attestation, review submission, or publication has been performed by this preparation task.

## Current official references

- [Build plugin packages](https://developers.openai.com/plugins/build/plugins)
- [Upload and submit your plugin](https://developers.openai.com/plugins/deploy/submission)
- [Listing and interface errors](https://developers.openai.com/plugins/deploy/submission-errors#listing-and-interface-errors)
- [Plugin guidelines](https://developers.openai.com/plugins/plugin-guidelines)
- [Agent Plugins manifest schema](https://agent-plugins.org/schemas/1.0.0/plugin.schema.json)
- [Agent Plugins MCP schema](https://agent-plugins.org/schemas/1.0.0/mcp.schema.json)

Checked on October 1, 2026. Dashboard findings remain authoritative for acceptance.
