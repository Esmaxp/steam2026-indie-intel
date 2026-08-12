"""Valve Top-Wishlists sweep — the ordinal, never a count.

Steam publishes no wishlist numbers, but it does publish the ORDER of the
most-wishlisted unreleased games. That order is a real, first-party,
unauthenticated observation, so this collector records it verbatim and
derives nothing from it.

What the rank is NOT: a wishlist count, and not convertible into one. Valve
blends total wishlists with recent velocity, so the ordering is not monotone
in wishlists and permutes locally from minute to minute. Small rank moves are
noise; only large sustained moves carry signal.

This list must NEVER feed discovery. It spans all of Steam and contains
released, DLC and hardware rows; admitting from it would poison the
indie catalogue.

Mechanics, each verified live against the endpoint on 2026-08-12:
  * `count` is clamped at 100 — requesting 200 returns 100 rows.
  * The echoed `data["start"]` is authoritative, NOT the requested value:
    start=150 with count=100 is floored to 100, so trusting the request
    would misrank an entire page. Past the end it echoes total_count - 1
    and returns zero rows.
  * `cc` must be pinned. Regional listings are order-preserving
    subsequences (cc=de retained 11/50 positions), so an unpinned cc
    silently shifts every rank below a removal.
  * The store rate-limits even at ~3s spacing, with no Retry-After.
"""

import datetime
import logging
from dataclasses import dataclass

import sqlalchemy as sa
from bs4 import BeautifulSoup

from app.db.session import async_session_factory
from app.models import WishlistRankEntry, WishlistRankSweep
from scraper.common.http import SteamClient, make_session
from scraper.discovery.search import SEARCH_URL, parse_search_row

logger = logging.getLogger(__name__)

PAGE_SIZE = 100          # server-side maximum; larger values are clamped
MAX_PAGES = 120          # hard stop: ~5.2k rows today, so this is generous
MIN_INTERVAL = 3.0       # measured: the store 429s even at this spacing
COUNTRY = "us"           # pinned — see module docstring

# rows_ingested must land within this of the endpoint's echoed total_count
# for the sweep to count as complete. Sub_ rows are legitimately dropped, and
# the chart shifts under us mid-sweep, so an exact match is not achievable.
TOTAL_TOLERANCE = 25
MIN_PLAUSIBLE_ROWS = 1000

BASE_PARAMS = {
    "query": "",
    "filter": "popularwishlist",
    "infinite": 1,
    "count": PAGE_SIZE,
    "cc": COUNTRY,
    "l": "english",
}


@dataclass(frozen=True)
class RankedApp:
    appid: int
    rank: int
    name: str


@dataclass
class SweepResult:
    entries: list[RankedApp]
    total_count: int | None
    pages_fetched: int
    dropped_non_app: int
    # Same appid seen at two ranks because the chart reshuffled mid-sweep.
    # Tracked separately from dropped_non_app so that every gap in the rank
    # sequence has a recorded cause — an unexplained gap should read as a bug.
    dropped_duplicate: int
    complete: bool
    notes: str
    started_at: datetime.datetime | None = None
    finished_at: datetime.datetime | None = None


def parse_rank_page(results_html: str, returned_start: int) -> tuple[list[RankedApp], int]:
    """(ranked rows, count of non-App rows dropped) for one page.

    `returned_start` MUST be the endpoint's echoed start, not the requested
    one — see module docstring.
    """
    soup = BeautifulSoup(results_html, "html.parser")
    anchors = soup.select("a.search_result_row")
    ranked: list[RankedApp] = []
    dropped = 0
    for offset, anchor in enumerate(anchors):
        row = parse_search_row(anchor)
        if row is None:
            # Sub_/Bundle_ rows still occupy an ordinal position on Valve's
            # side, so the offset is not compacted — later ranks keep their
            # true positions and the gap is recorded instead.
            dropped += 1
            continue
        ranked.append(
            RankedApp(appid=row.appid, rank=returned_start + offset + 1, name=row.name)
        )
    return ranked, dropped


async def fetch_rank_sweep(client: SteamClient) -> SweepResult:
    """Page the whole chart. Never raises for a partial result — the caller
    decides what a short sweep means."""
    entries: list[RankedApp] = []
    seen: set[int] = set()
    total_count: int | None = None
    dropped_non_app = 0
    dropped_duplicate = 0
    pages = 0
    notes: list[str] = []
    start = 0
    # Wall-clock from Python, not func.now(): the whole persist runs in one
    # transaction, so server-side now() would give both timestamps the same
    # value and report a multi-minute sweep as lasting zero seconds.
    started_at = datetime.datetime.now(datetime.timezone.utc)

    def _result(complete: bool) -> SweepResult:
        return SweepResult(
            entries, total_count, pages, dropped_non_app, dropped_duplicate,
            complete, "; ".join(notes),
            started_at, datetime.datetime.now(datetime.timezone.utc),
        )

    for _ in range(MAX_PAGES):
        try:
            data = await client.get_json(SEARCH_URL, params={**BASE_PARAMS, "start": start})
        except Exception as exc:  # noqa: BLE001 — any failure ends the sweep as partial
            notes.append(f"page at start={start} failed: {exc.__class__.__name__}: {exc}")
            return _result(False)

        if not data.get("success"):
            notes.append(f"success={data.get('success')!r} at start={start}")
            return _result(False)

        pages += 1
        total_count = int(data.get("total_count") or 0) or total_count
        returned_start = int(data.get("start", start))
        page_entries, dropped = parse_rank_page(data.get("results_html", ""), returned_start)
        dropped_non_app += dropped

        if not page_entries and dropped == 0:
            break  # genuine end of list

        for entry in page_entries:
            # The chart reshuffles under a multi-minute sweep, so the same
            # appid can appear on two pages. First position wins; a later
            # duplicate is drift, not a new game.
            if entry.appid in seen:
                dropped_duplicate += 1
                continue
            seen.add(entry.appid)
            entries.append(entry)

        rows_on_page = len(page_entries) + dropped
        if total_count and returned_start + rows_on_page >= total_count:
            break
        if rows_on_page == 0:
            break
        start = returned_start + rows_on_page
    else:
        notes.append(f"hit MAX_PAGES={MAX_PAGES} before the end of the chart")

    return _result(True)


def validate(result: SweepResult) -> tuple[bool, str]:
    """Decide complete vs partial. A silently-empty sweep is the dangerous
    failure: it would flip the whole catalogue to "Not ranked" overnight and
    manufacture enormous fake rank deltas, so the bar is deliberately high."""
    problems: list[str] = []
    if not result.complete:
        problems.append("sweep did not reach the end of the chart")
    if len(result.entries) < MIN_PLAUSIBLE_ROWS:
        problems.append(
            f"only {len(result.entries)} rows (< {MIN_PLAUSIBLE_ROWS}) — "
            "possible markup change breaking data-ds-itemkey"
        )
    if result.total_count:
        accounted = len(result.entries) + result.dropped_non_app + result.dropped_duplicate
        drift = abs(accounted - result.total_count)
        if drift > TOTAL_TOLERANCE:
            problems.append(
                f"row count off by {drift} from total_count={result.total_count} "
                f"(tolerance {TOTAL_TOLERANCE})"
            )
    return (not problems), "; ".join(problems)


async def run_rank_sweep(dry_run: bool = False) -> dict:
    async with make_session() as http:
        client = SteamClient(http, min_interval=MIN_INTERVAL)
        result = await fetch_rank_sweep(client)

    ok, problems = validate(result)
    status = "complete" if ok else ("failed" if not result.entries else "partial")
    # Every rank gap must have a recorded cause, so both drop reasons are
    # written to notes even when zero would be unremarkable.
    parts = [n for n in (result.notes, problems) if n]
    if result.dropped_non_app:
        parts.append(f"dropped {result.dropped_non_app} non-App rows (packages/bundles)")
    if result.dropped_duplicate:
        parts.append(
            f"dropped {result.dropped_duplicate} duplicate appids (chart reshuffled mid-sweep)"
        )
    notes = "; ".join(parts) or None

    summary = {
        "status": status,
        "rows": len(result.entries),
        "total_count": result.total_count,
        "pages": result.pages_fetched,
        "dropped_non_app": result.dropped_non_app,
        "dropped_duplicate": result.dropped_duplicate,
        "notes": notes,
    }
    if dry_run:
        summary["persisted"] = False
        return summary

    # One transaction for the whole sweep: a crashed run must leave no
    # half-snapshot behind for Step E to difference against.
    async with async_session_factory() as db:
        sweep = WishlistRankSweep(
            cc=COUNTRY,
            total_count=result.total_count,
            rows_ingested=len(result.entries),
            status=status,
            source_url=SEARCH_URL,
            notes=notes,
            started_at=result.started_at,
        )
        db.add(sweep)
        await db.flush()

        if result.entries:
            await db.execute(
                sa.insert(WishlistRankEntry),
                [
                    {"sweep_id": sweep.id, "appid": e.appid, "rank": e.rank, "name": e.name}
                    for e in result.entries
                ],
            )
        sweep.finished_at = result.finished_at
        await db.commit()
        summary["sweep_id"] = sweep.id

    summary["persisted"] = True
    logger.info("Rank sweep: %s", summary)
    return summary
