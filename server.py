#!/usr/bin/env python3
"""Entrypoint for the LLMQA web dashboard.

    python server.py          # local dev
    uvicorn llmqa.web.app:app # equivalent

Honors $PORT (Railway) and $HOST.
"""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()  # load .env if present

import uvicorn


def _truthy(val: str | None) -> bool:
    # "0"/"false"/"" are falsey; only explicit truthy strings enable reload.
    return (val or "").strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    uvicorn.run(
        "llmqa.web.app:app",
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8080")),
        reload=_truthy(os.environ.get("LLMQA_RELOAD")),
    )
