# Build context is the repo root (see docker-compose.yml's `api` service:
# `build.context: .`, `build.dockerfile: api/Dockerfile`) so this can vendor
# the sibling ingestion/ingestion package into the image — it has no
# packaging metadata (setup.py/pyproject.toml) to `pip install -e` it, same
# "copy source in" idiom ingestion/Dockerfile already uses for its own code.
FROM python:3.12-slim

WORKDIR /app

COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Only the pure query/recommendation modules are imported here (no jobs/*.py,
# so no TA-Lib/pandas build needed) — see app/config.py and the routers for
# exactly which ingestion.* modules this service touches.
COPY ingestion/ingestion ./ingestion
COPY api/app ./app

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
