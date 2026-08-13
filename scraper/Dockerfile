# Build from repo root:  docker build -f scraper/Dockerfile .
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/srv

WORKDIR /srv

COPY backend/pyproject.toml backend/
COPY backend/app backend/app
# Both extras: `similarity` for the offline TF-IDF dimension fallback, `dev`
# for pytest — this image also backs the `tests` compose service.
RUN pip install --upgrade pip && pip install "./backend[dev,similarity]"

COPY scraper scraper
COPY workers workers

ENV PYTHONPATH=/srv
CMD ["python", "-m", "scraper.discovery.run", "--mode", "search"]
