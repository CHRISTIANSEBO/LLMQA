#!/usr/bin/env python3
"""Entrypoint for the LLMQA web dashboard.

    python server.py          # local dev
    uvicorn llmqa.web.app:app # equivalent

Honors $PORT (Railway) and $HOST.
"""
from __future__ import annotations

import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "llmqa.web.app:app",
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8000")),
        reload=bool(os.environ.get("LLMQA_RELOAD")),
    )
