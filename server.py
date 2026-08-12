#!/usr/bin/env python3
"""Entrypoint for the LLMQA web dashboard.

    python server.py            # local dev
    python -m llmqa.web         # equivalent (pip-installed copy)
    uvicorn llmqa.web.app:app   # equivalent

Honors $PORT (Railway/most PaaS) and $HOST. This is a thin shim over
``llmqa.web.__main__.main`` so the deploy entrypoint and the module entrypoint
share one implementation (and one default port).
"""
from __future__ import annotations

from llmqa.web.__main__ import main

if __name__ == "__main__":
    main()
