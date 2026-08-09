"""Run the LLMQA web dashboard as a module: ``python -m llmqa.web``.

This mirrors the top-level ``server.py`` dev entrypoint so a pip-installed copy
(where ``server.py`` isn't on the path) has a first-class way to start the
dashboard. Honors ``$PORT`` (Railway) and ``$HOST``.
"""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()  # load .env if present

import uvicorn


def _truthy(val: str | None) -> bool:
    return (val or "").strip().lower() in {"1", "true", "yes", "on"}


def main() -> None:
    uvicorn.run(
        "llmqa.web.app:app",
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8000")),
        reload=_truthy(os.environ.get("LLMQA_RELOAD")),
    )


if __name__ == "__main__":
    main()
