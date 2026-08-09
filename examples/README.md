# Examples

Runnable, self-contained examples. All of them use the free, deterministic
`mock` provider, so they need **no API key**.

```bash
pip install llmqa            # or: pip install -e ".[all]" from a source checkout
```

| File | Shows |
|------|-------|
| [`custom_dataset.py`](custom_dataset.py) | Run an evaluation over your own dataset file, programmatically. |
| [`custom_dataset.yaml`](custom_dataset.yaml) | A tiny hand-written golden dataset (validate against `../datasets/dataset.schema.json`). |
| [`compare_providers.py`](compare_providers.py) | Run two providers on the same dataset and diff their pass rates. |
| [`custom_provider.py`](custom_provider.py) | Plug in a brand-new provider without modifying the package. |

For a copy-paste **GitHub Actions workflow** that gates a PR on quality, use the
canonical template at
[`../.github/workflows/llmqa-example.yml`](../.github/workflows/llmqa-example.yml).

Run any script directly:

```bash
python examples/custom_dataset.py
python examples/compare_providers.py
python examples/custom_provider.py
```

See [`../docs/extending.md`](../docs/extending.md) for the full guide to adding
datasets, metrics, and providers.
