# LLMQA dashboard — single-service container.
# Build:  docker build -t llmqa .
# Run:    docker run -p 8000:8000 llmqa
# Enable real providers:  -e LLMQA_ALLOW_REAL_PROVIDERS=1 -e OPENAI_API_KEY=...
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app

# Install deps first for better layer caching.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# App source.
COPY llmqa ./llmqa
COPY datasets ./datasets
COPY cli.py server.py ./

EXPOSE 8000

# Basic container healthcheck against the liveness endpoint.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os,urllib.request;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/api/health').read()" || exit 1

# server.py honors $PORT (Railway/most PaaS set it).
CMD ["python", "server.py"]
