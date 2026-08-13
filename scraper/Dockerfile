# Build from repo root:  docker build -f scraper/Dockerfile .
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/srv

WORKDIR /srv

COPY backend/pyproject.toml backend/
COPY backend/app backend/app
RUN pip install --upgrade pip && pip install "./backend[similarity]"

COPY scraper scraper
COPY workers workers

ENV PYTHONPATH=/srv
CMD ["python", "-m", "scraper.discovery.run", "--mode", "search"]
