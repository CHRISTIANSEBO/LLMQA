# Security Policy

## Reporting a vulnerability

If you discover a security issue in LLMQA, please report it responsibly:

- **Preferred:** open a
  [GitHub security advisory](https://github.com/CHRISTIANSEBO/LLMQA/security/advisories/new)
  (private).
- Alternatively, open a regular issue **without** sensitive exploit details and
  ask a maintainer for a private channel.

Please do not disclose the issue publicly until it has been addressed. We aim
to acknowledge reports promptly and will keep you updated on the fix.

## API keys and the hosted demo

LLMQA is designed to run **without any API key** — the deterministic `mock`
providers power the full test suite, the CI self-eval gate, and the dashboard's
default experience.

- **The hosted demo runs the free `mock` provider only.** It does not expose a
  maintainer's paid API key, so public visitors cannot incur third-party model
  costs.
- **Live providers are bring-your-own-key.** To evaluate a real model, clone
  the repo and set the relevant key in your own environment
  (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or `XAI_API_KEY`). Keys are read from
  the environment and are never committed — `.env` is gitignored.

If you self-host with a live key, treat that deployment like any keyed service:
restrict access and monitor usage, since each live run calls a paid API.
