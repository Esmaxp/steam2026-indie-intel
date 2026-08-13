"""Optional, opt-in text pass: estimate 2D/2.5D/3D from metadata similarity.

Third and last step of the dimension ladder, after the free rule-based pass
(scraper/classifiers/classify.py, replayed by workers/reclassify_classification.py)
and the screenshot pass (workers/classify_dimension_vision.py). It exists for
the games those two cannot settle: no store dimension tag, no conclusive
camera/graphics combination, and either no screenshot at all or a screenshot
the vision pass could not read.

Unlike the other two, this worker does not observe the game — it *estimates*
by similarity, asking the model which comparable titles (genre, tags,
developer track record, engine, era) the game most resembles and what
dimension those use. That is a weaker kind of evidence than a tag or a
screenshot, so results are written with dimension_source = "similarity_ai",
kept distinct from "vision_ai" and never overwriting either.

Like the vision worker, each call costs real Anthropic API money, so this one:

- is gated behind ANTHROPIC_API_KEY (not configured by default),
- never runs as part of the collector/pipeline chain — manual batches only,
- only touches games still `dimension = unknown` that carry store data,
- accepts the model's own "unknown" answer: a game with too little signal
  stays unknown rather than getting a fabricated dimension.

Usage:
    python -m workers.classify_dimension_similarity [--limit 100]
        [--min-confidence low|medium|high] [--only-without-screenshots]
    docker compose run --rm dimension_similarity
"""

import argparse
import asyncio
import json
from dataclasses import dataclass

import aiohttp
import sqlalchemy as sa
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.db.session import async_session_factory
from app.models import Dimension, Game, GameEngine, MediaAsset, MediaType
from scraper.common.logging import setup_logging

API_URL = "https://api.anthropic.com/v1/messages"
REQUEST_PAUSE_SECONDS = 1.0
FAILURE_STOP_STREAK = 3
PROGRESS_EVERY = 25
MAX_TAGS = 12  # tags are rank-ordered; the tail adds noise, not signal

_ANSWER_TO_DIMENSION = {
    "2d": Dimension.TWO_D,
    "2.5d": Dimension.TWO_HALF_D,
    "3d": Dimension.THREE_D,
}
_CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}

_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "dimension": {"type": "string", "enum": ["2d", "2.5d", "3d", "unknown"]},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "reason": {"type": "string"},
    },
    "required": ["dimension", "confidence", "reason"],
    "additionalProperties": False,
}

# Kept verbatim from promt.md — the placeholders are filled by _render() with
# str.replace rather than str.format, so the literal JSON braces below need no
# escaping and the text stays diff-able against its source.
_PROMPT_TEMPLATE = """You are classifying a video game's visual dimensionality as "2d", "2.5d", or "3d".

No definitive signal exists for this game (no store dimension tag, no
conclusive camera/graphics-style combination, no screenshot available or
screenshot itself was inconclusive). Your task is different from a
factual lookup: estimate the most likely dimension by reasoning from
similarity — drawing on your knowledge of comparable games (same genre,
similar name/theme, same developer/publisher, same engine, same era,
same tag combination) to infer what this game most plausibly looks like.

Definitions:
- "2d": flat sprite/vector-based visuals, side-view or top-down, no
  true 3D-rendered depth (e.g. classic platformers, 2D metroidvanias).
- "2.5d": 2D gameplay/sprites presented with 3D-rendered depth or
  perspective (isometric pixel art, 2D character in a 3D environment,
  parallax-layered 3D backgrounds).
- "3d": fully 3D-rendered models, environments, and camera (first/third
  person, real-time 3D world).

Game data:
- Name: {name}
- Short description: {short_description}
- Genres/tags: {genres_and_tags}
- Developer/Publisher: {developer_publisher}
- Engine (if known): {engine}
- Release year (if known): {release_year}

Instructions:
1. Think about which well-known games this title most closely resembles
   based on genre, name, tags, developer track record, and engine — and
   what dimension those comparable games use.
2. If the signals point clearly in one direction, answer with that
   dimension and a confidence level.
3. If the signals are genuinely too weak or contradictory to form a
   reasonable estimate (e.g. a generic name with only one vague tag),
   answer "unknown" rather than guessing blindly — but prefer a
   low-confidence answer over "unknown" whenever you have *any*
   genuine similarity signal to reason from.
4. Do not rely on outside knowledge you are not confident in; do not
   invent facts about the game that were not given to you.

Respond only with JSON matching this schema:
{
  "dimension": "2d" | "2.5d" | "3d" | "unknown",
  "confidence": "low" | "medium" | "high",
  "reason": "one sentence citing the specific similarity signal(s) used"
}"""


@dataclass(frozen=True)
class Candidate:
    appid: int
    name: str
    short_description: str
    genres_and_tags: str
    developer_publisher: str
    engine: str
    release_year: str


def _render(candidate: Candidate) -> str:
    prompt = _PROMPT_TEMPLATE
    for field, value in (
        ("{name}", candidate.name),
        ("{short_description}", candidate.short_description),
        ("{genres_and_tags}", candidate.genres_and_tags),
        ("{developer_publisher}", candidate.developer_publisher),
        ("{engine}", candidate.engine),
        ("{release_year}", candidate.release_year),
    ):
        prompt = prompt.replace(field, value or "unknown")
    return prompt


def _to_candidate(game: Game) -> Candidate:
    genres = [g.name for g in game.genres]
    tags = [t.name for t in game.tags][:MAX_TAGS]
    developers = [d.name for d in game.developers]
    publishers = [p.name for p in game.publishers]
    return Candidate(
        appid=game.appid,
        name=game.name,
        short_description=(game.short_description or "").strip(),
        genres_and_tags=", ".join(dict.fromkeys(genres + tags)),
        developer_publisher=" / ".join(
            filter(None, [", ".join(developers), ", ".join(publishers)])
        ),
        engine="" if game.engine is GameEngine.UNKNOWN else game.engine.value,
        release_year=str(game.release_date.year) if game.release_date else "",
    )


async def select_candidates(limit: int, only_without_screenshots: bool) -> list[Candidate]:
    """Games still unknown after the rule-based and vision passes.

    Requires store data (last_synced_at) — an uncollected game has no
    description, genres or tags, so there would be nothing to reason from.
    """
    has_screenshot = sa.exists().where(
        MediaAsset.appid == Game.appid, MediaAsset.media_type == MediaType.SCREENSHOT
    )
    async with async_session_factory() as db:
        stmt = (
            sa.select(Game)
            .options(
                selectinload(Game.genres),
                selectinload(Game.tags),
                selectinload(Game.developers),
                selectinload(Game.publishers),
            )
            .where(
                Game.dimension == Dimension.UNKNOWN,
                # Idempotency, same guard as reclassify_classification: never touch
                # rows another source already settled (tag / rule_based /
                # vision_ai / a previous run of this worker).
                sa.or_(Game.dimension_source.is_(None), Game.dimension_source == "unknown"),
                Game.last_synced_at.is_not(None),
            )
            .order_by(Game.appid)
            .limit(limit)
        )
        if only_without_screenshots:
            stmt = stmt.where(~has_screenshot)
        games = (await db.execute(stmt)).scalars().all()
        return [_to_candidate(game) for game in games]


async def count_with_screenshots(appids: list[int]) -> int:
    """How many of these could the (stronger) vision pass still settle."""
    if not appids:
        return 0
    async with async_session_factory() as db:
        stmt = (
            sa.select(sa.func.count(sa.distinct(MediaAsset.appid)))
            .where(
                MediaAsset.appid.in_(appids),
                MediaAsset.media_type == MediaType.SCREENSHOT,
            )
        )
        return int((await db.execute(stmt)).scalar_one())


async def classify_by_similarity(
    http: aiohttp.ClientSession, api_key: str, model: str, candidate: Candidate
) -> tuple[Dimension | None, str, str]:
    """Returns (dimension, confidence, note). dimension is None when the call
    gave no usable answer (deliberate "unknown", refusal, truncation, parse
    failure) — never raises for those; the game simply stays unknown."""
    payload = {
        "model": model,
        "max_tokens": 2048,  # hard cap on thinking + answer; answer itself is tiny
        "output_config": {
            "effort": "low",  # narrow classification — no deep reasoning needed
            "format": {"type": "json_schema", "schema": _OUTPUT_SCHEMA},
        },
        "messages": [{"role": "user", "content": _render(candidate)}],
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
            return None, "", f"HTTP {res.status}: {body.get('error', {}).get('message', '')[:120]}"

    # Safety classifiers can decline (HTTP 200 + stop_reason "refusal") —
    # check before reading content.
    if body.get("stop_reason") == "refusal":
        return None, "", "refusal"
    text = next(
        (block["text"] for block in body.get("content", []) if block.get("type") == "text"),
        None,
    )
    if not text:
        return None, "", f"no text block (stop_reason={body.get('stop_reason')})"
    try:
        answer = json.loads(text)
    except json.JSONDecodeError:
        return None, "", "unparseable answer"

    raw_dimension = str(answer.get("dimension", "")).lower()
    confidence = str(answer.get("confidence", "")).lower()
    reason = str(answer.get("reason", ""))[:200]
    if raw_dimension == "unknown":
        # An honest refusal to guess — the schema allows it on purpose.
        return None, confidence, f"model answered unknown: {reason}"
    dimension = _ANSWER_TO_DIMENSION.get(raw_dimension)
    if dimension is None:
        return None, confidence, f"unexpected answer {answer.get('dimension')!r}"
    return dimension, confidence, reason


async def run(limit: int, min_confidence: str, only_without_screenshots: bool) -> None:
    logger = setup_logging("classify_dimension_similarity")
    settings = get_settings()
    if not settings.anthropic_api_key:
        logger.warning(
            "ANTHROPIC_API_KEY is not configured — this opt-in worker does "
            "nothing without it. Run the free rule-based pass (the store "
            "collector, or workers.reclassify_classification) and the screenshot "
            "pass (dimension_vision) first; only use this for what is left."
        )
        return

    candidates = await select_candidates(limit, only_without_screenshots)
    if not candidates:
        logger.info("No unknown-dimension games with store data — nothing to do.")
        return

    if not only_without_screenshots:
        with_shots = await count_with_screenshots([c.appid for c in candidates])
        if with_shots:
            logger.info(
                "%d of %d candidates still have a screenshot — the vision pass "
                "(dimension_vision) reads those directly and is stronger "
                "evidence than similarity; use --only-without-screenshots to "
                "leave them for it.",
                with_shots, len(candidates),
            )
    logger.info(
        "Similarity-classifying %d games (model %s, min confidence %s)",
        len(candidates), settings.anthropic_text_model, min_confidence,
    )

    threshold = _CONFIDENCE_RANK[min_confidence]
    classified = skipped = below_threshold = 0
    failure_streak = 0
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as http:
        for index, candidate in enumerate(candidates, start=1):
            try:
                dimension, confidence, note = await classify_by_similarity(
                    http, settings.anthropic_api_key,
                    settings.anthropic_text_model, candidate,
                )
                failure_streak = 0
            except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError) as exc:
                failure_streak += 1
                logger.warning("appid %s failed: %s", candidate.appid, exc)
                if failure_streak >= FAILURE_STOP_STREAK:
                    logger.error(
                        "%d consecutive API failures — stopping at %d/%d.",
                        FAILURE_STOP_STREAK, index, len(candidates),
                    )
                    break
                continue

            if dimension is None:
                skipped += 1
                logger.info("appid %s left unknown (%s)", candidate.appid, note)
            elif _CONFIDENCE_RANK.get(confidence, 0) < threshold:
                below_threshold += 1
                logger.info(
                    "appid %s -> %s discarded: confidence %s below %s (%s)",
                    candidate.appid, dimension.value, confidence or "missing",
                    min_confidence, note,
                )
            else:
                async with async_session_factory() as db:
                    await db.execute(
                        sa.update(Game)
                        .where(Game.appid == candidate.appid)
                        .values(dimension=dimension, dimension_source="similarity_ai")
                    )
                    await db.commit()
                classified += 1
                logger.debug(
                    "appid %s -> %s (%s confidence: %s)",
                    candidate.appid, dimension.value, confidence, note,
                )

            if index % PROGRESS_EVERY == 0 or index == len(candidates):
                logger.info(
                    "Progress %d/%d — classified %d, left unknown %d, below threshold %d",
                    index, len(candidates), classified, skipped, below_threshold,
                )
            await asyncio.sleep(REQUEST_PAUSE_SECONDS)

    logger.info(
        "Done: %d classified via similarity, %d left unknown (model declined "
        "or the call returned no usable answer), %d discarded below the %s "
        "confidence threshold.",
        classified, skipped, below_threshold, min_confidence,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Estimate 2D/3D by metadata similarity for games no tag, "
        "rule or screenshot could settle"
    )
    parser.add_argument(
        "--limit", type=int, default=100,
        help="max games this run (each costs a real API call)",
    )
    parser.add_argument(
        "--min-confidence", choices=["low", "medium", "high"], default="low",
        help="discard answers the model itself rates below this (default low = "
        "keep every non-unknown answer)",
    )
    parser.add_argument(
        "--only-without-screenshots", action="store_true",
        help="skip games that still have a screenshot, leaving them to the "
        "stronger vision pass (dimension_vision)",
    )
    args = parser.parse_args()
    asyncio.run(run(args.limit, args.min_confidence, args.only_without_screenshots))


if __name__ == "__main__":
    main()
