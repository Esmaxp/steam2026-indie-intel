# Build from the REPO ROOT:  docker build -f backend/Dockerfile .
# (The context is the repo, not backend/, because the API runs the collectors
# in-process for admin-triggered sweeps and therefore needs scraper/ and
# workers/ importable.)
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY backend/pyproject.toml ./
COPY backend/app ./app
COPY backend/alembic.ini ./
COPY backend/alembic ./alembic

RUN pip install --upgrade pip && pip install .

# Collector packages for /admin/sweeps. They import from `app`, never the
# reverse, so there is no cycle.
COPY scraper ./scraper
COPY workers ./workers

EXPOSE 8000

# Apply migrations, then start the API.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
