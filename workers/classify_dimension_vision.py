"""Optional, opt-in vision pass: classify 2D/2.5D/3D from a screenshot.

Last-resort enrichment for games where the rule-based classifier (tags,
camera, graphics style, description — see scraper/classifiers/classify.py)
left `dimension` unknown. Each call costs real Anthropic API money, so this
worker:

- is gated behind ANTHROPIC_API_KEY (not configured by default),
- never runs as part of the collector/pipeline chain — manual batches only,
- only touches games still `dimension = unknown` that have a screenshot.

The Claude Messages API is called with one screenshot (thumbnail — cheaper,
and plenty to tell 2D from 3D) and a narrow classification prompt; structured
output pins the answer to exactly {"dimension": "2d"|"2.5d"|"3d", "reason"}.
Results are written with dimension_source = "vision_ai".

Usage:
    python -m workers.classify_dimension_vision [--limit 100]
    docker compose run --rm dimension_vision
"""

import argparse
import asyncio
import json

import aiohttp
import sqlalchemy as sa

from app.core.config import get_settings
from app.db.session import async_session_factory
from app.models import Dimension, Game, MediaAsset, MediaType
from scraper.common.logging import setup_logging

API_URL = "https://api.anthropic.com/v1/messages"
REQUEST_PAUSE_SECONDS = 1.0
FAILURE_STOP_STREAK = 3
PROGRESS_EVERY = 25

_ANSWER_TO_DIMENSION = {
    "2d": Dimension.TWO_D,
    "2.5d": Dimension.TWO_HALF_D,
    "3d": Dimension.THREE_D,
}

_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "dimension": {"type": "string", "enum": ["2d", "2.5d", "3d"]},
        "reason": {"type": "string"},
    },
    "required": ["dimension", "reason"],
    "additionalProperties": False,
}

_PROMPT = (
    "Look at this game screenshot. Is the game's visual presentation 2d, "
    "2.5d (2D gameplay with 3D-rendered or isometric depth), or 3d? "
    "Answer with the single word plus a one-line reason."
)


async def select_candidates(limit: int) -> list[tuple[int, str]]:
    """Games still unknown after the rule-based pass, with a screenshot."""
    async with async_session_factory() as db:
        stmt = (
            sa.select(Game.appid, sa.func.coalesce(MediaAsset.thumbnail_url, MediaAsset.url))
            .join(MediaAsset, MediaAsset.appid == Game.appid)
            .where(
                Game.dimension == Dimension.UNKNOWN,
                MediaAsset.media_type == MediaType.SCREENSHOT,
            )
            .distinct(Game.appid)
            .order_by(Game.appid, MediaAsset.position)
            .limit(limit)
        )
        return [(appid, url) for appid, url in (await db.execute(stmt)).all()]


async def classify_screenshot(
    http: aiohttp.ClientSession, api_key: str, model: str, screenshot_url: str
) -> tuple[Dimension | None, str]:
    """Returns (dimension, note). dimension is None when the call gave no
    usable answer (refusal, truncation, parse failure) — never raises for
    those; the game simply stays unknown."""
    payload = {
        "model": model,
        "max_tokens": 2048,  # hard cap on thinking + answer; answer itself is tiny
        "output_config": {
            "effort": "low",  # narrow classification — no deep reasoning needed
            "format": {"type": "json_schema", "schema": _OUTPUT_SCHEMA},
        },
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "url", "url": screenshot_url}},
                    {"type": "text", "text": _PROMPT},
                ],
            }
        ],
    }
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    async with http.post(API_URL, json=payload, headers=headers) as res:
        if res.status == 429 or res.status >= 500:
            raise RuntimeError(f"retryable HTTP {res.status}")
        body = await res.json()
        if res.status != 200:
            return None, f"HTTP {res.status}: {body.get('error', {}).get('message', '')[:120]}"

    # Safety classifiers can decline (HTTP 200 + stop_reason "refusal") —
    # check before reading content.
    if body.get("stop_reason") == "refusal":
        return None, "refusal"
    text = next(
        (block["text"] for block in body.get("content", []) if block.get("type") == "text"),
        None,
    )
    if not text:
        return None, f"no text block (stop_reason={body.get('stop_reason')})"
    try:
        answer = json.loads(text)
    except json.JSONDecodeError:
        return None, "unparseable answer"
    dimension = _ANSWER_TO_DIMENSION.get(str(answer.get("dimension", "")).lower())
    if dimension is None:
        return None, f"unexpected answer {answer.get('dimension')!r}"
    return dimension, str(answer.get("reason", ""))[:200]


async def run(limit: int) -> None:
    logger = setup_logging("classify_dimension_vision")
    settings = get_settings()
    if not settings.anthropic_api_key:
        logger.warning(
            "ANTHROPIC_API_KEY is not configured — this opt-in worker does "
            "nothing without it. Run the free rule-based pass (the store "
            "collector) first; only use this for games still unknown."
        )
        return

    candidates = await select_candidates(limit)
    if not candidates:
        logger.info("No unknown-dimension games with screenshots — nothing to do.")
        return
    logger.info(
        "Vision-classifying %d games (model %s)",
        len(candidates), settings.anthropic_vision_model,
    )

    classified = skipped = 0
    failure_streak = 0
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as http:
        for index, (appid, screenshot_url) in enumerate(candidates, start=1):
            try:
                dimension, note = await classify_screenshot(
                    http, settings.anthropic_api_key,
                    settings.anthropic_vision_model, screenshot_url,
                )
                failure_streak = 0
            except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError) as exc:
                failure_streak += 1
                logger.warning("appid %s failed: %s", appid, exc)
                if failure_streak >= FAILURE_STOP_STREAK:
                    logger.error(
                        "%d consecutive API failures — stopping at %d/%d.",
                        FAILURE_STOP_STREAK, index, len(candidates),
                    )
                    break
                continue

            if dimension is None:
                skipped += 1
                logger.info("appid %s left unknown (%s)", appid, note)
            else:
                async with async_session_factory() as db:
                    await db.execute(
                        sa.update(Game)
                        .where(Game.appid == appid)
                        .values(dimension=dimension, dimension_source="vision_ai")
                    )
                    await db.commit()
                classified += 1
                logger.debug("appid %s -> %s (%s)", appid, dimension.value, note)

            if index % PROGRESS_EVERY == 0 or index == len(candidates):
                logger.info(
                    "Progress %d/%d — classified %d, left unknown %d",
                    index, len(candidates), classified, skipped,
                )
            await asyncio.sleep(REQUEST_PAUSE_SECONDS)

    logger.info("Done: %d classified via vision, %d left unknown.", classified, skipped)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Vision-classify 2D/3D for games the rule-based pass left unknown"
    )
    parser.add_argument(
        "--limit", type=int, default=100,
        help="max games this run (each costs a real API call)",
    )
    args = parser.parse_args()
    asyncio.run(run(args.limit))


if __name__ == "__main__":
    main()
