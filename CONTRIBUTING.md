# Contributing to LLMQA

Thanks for your interest in improving LLMQA! It's an open-source LLM
evaluation harness, and contributions of every size are welcome — bug fixes,
new metrics, new providers, more golden-dataset cases, docs, or ideas.

This guide gets you from a fresh clone to a passing test run and a clean pull
request.

## Ground rules

- **Be kind.** See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
- **No secrets in commits.** Never commit API keys, `.env` files, or run
  databases. `.env` and `*.db` are already gitignored — keep it that way.
- **Everything must pass key-free.** The `mock` providers are deterministic and
  need no API key, so tests and the self-eval gate run for free in CI. Don't
  add changes that require a paid key to test.

## Development setup

LLMQA targets **Python 3.11+** (see `.python-version`).

```bash
git clone https://github.com/CHRISTIANSEBO/LLMQA.git
cd LLMQA

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt   # runtime + test deps
```

Sanity check — this should pass with no key:

```bash
pytest tests/ -v
python cli.py run --provider mock --min-pass-rate 0.8 --no-store
```

Run the dashboard locally:

```bash
python server.py            # -> http://localhost:8000
```

## The two CI gates

Every push and pull request runs [`.github/workflows/tests.yml`](.github/workflows/tests.yml),
which enforces two things. Run both locally before opening a PR:

1. **Unit + web tests** — the harness itself is tested.

   ```bash
   pytest tests/ -v
   ```

2. **Self-eval quality gate** — the mock golden run must keep an ≥80% pass rate.

   ```bash
   python cli.py run --provider mock --min-pass-rate 0.8 --no-store
   ```

If either fails, the PR will be red. Both are deterministic and key-free, so a
green local run means a green CI run.

## How to contribute common changes

### Add a metric

1. Create `llmqa/metrics/<your_metric>.py` subclassing the base metric in
   `llmqa/metrics/base.py`.
2. Register it so it's selectable via `--metrics`.
3. Add tests in `tests/test_metrics.py`.
4. Document it in the **Metrics** table in `README.md`.

### Add a provider

1. Create `llmqa/providers/<name>_provider.py` subclassing the base in
   `llmqa/providers/base.py`. Read its key from the environment; the harness
   must still run key-free on `mock`.
2. Wire it into provider selection so `--provider <name>` works.
3. Add tests (see `tests/test_openai_xai_providers.py` for the pattern —
   mock the network, don't hit a live API in CI).
4. Document it in `README.md` (the "Run against a real model" section).

### Add golden dataset cases

1. Edit `datasets/qa_golden.yaml`. Give each case an `id`, `input`,
   `expected`, and relevant `tags`. Use `gate_metrics` when only certain
   metrics should decide pass/fail (e.g. a summary shouldn't fail on exact
   string match).
2. Make sure `python cli.py run --provider mock` still passes the gate — the
   deterministic mock is tuned to the golden set, so new cases may need their
   `gate_metrics` set thoughtfully.

## Pull request checklist

- [ ] Branch off `main` with a descriptive name (e.g. `feat/embedding-similarity`).
- [ ] `pytest tests/ -v` passes.
- [ ] `python cli.py run --provider mock --min-pass-rate 0.8 --no-store` passes.
- [ ] New behavior has tests.
- [ ] `README.md` updated if you changed usage, metrics, providers, or the CLI.
- [ ] No secrets, `.env`, or `*.db` files staged.
- [ ] Commit messages are clear (conventional-commit style like `feat:` / `fix:`
      / `docs:` is appreciated but not required).

Open the PR against `main` and describe **what** changed and **why**. Draft PRs
are welcome if you'd like early feedback.

## Reporting bugs and requesting features

Use the GitHub issue templates. Please include:

- What you ran (command / provider / dataset).
- What you expected vs. what happened.
- Python version and OS.

Thanks for helping make LLM quality measurable and reviewable. 🎯
