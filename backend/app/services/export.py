"""Phase 8: export the filtered games list as CSV / Excel / JSON / Markdown.

Reuses the exact same filter/sort pipeline as GET /api/v1/games, so what you
see in the table is what you export. Flat formats (CSV/XLSX/MD) carry the
provenance columns (status + source) next to every wishlist/revenue/budget
value; the JSON format keeps the full structured provenance objects.
"""

import datetime
import io

import pandas as pd

from app.schemas.game import GameListItem

EXPORT_ROW_CAP = 50_000

MEDIA_TYPES = {
    "csv": "text/csv; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "json": "application/json",
    "md": "text/markdown; charset=utf-8",
}


def _flatten(item: GameListItem) -> dict:
    return {
        "appid": item.appid,
        "name": item.name,
        "developers": ", ".join(item.developers),
        "publishers": ", ".join(item.publishers),
        "release_date": item.release_date.isoformat() if item.release_date else None,
        "release_date_raw": item.release_date_raw,
        "released": item.is_released,
        "coming_soon": item.coming_soon,
        "early_access": item.early_access,
        "demo_available": item.demo_available,
        "demo_release_date": (
            item.demo_release_date.isoformat() if item.demo_release_date else None
        ),
        "next_fest": item.next_fest,
        "genres": ", ".join(item.genres),
        "steam_tags": ", ".join(item.tags),
        "dimension": item.dimension,
        "camera": item.camera,
        "graphics_style": item.graphics_style,
        "engine": item.engine,
        "indie_confidence": item.indie_confidence,
        "low_quality_signal": item.low_quality_signal,
        "is_free": item.is_free,
        "currency": item.currency,
        "current_price": (
            item.current_price_cents / 100 if item.current_price_cents is not None else None
        ),
        "total_reviews": item.total_reviews,
        "positive_pct": item.positive_pct,
        "review_score": item.review_score_desc,
        "peak_ccu": item.peak_ccu,
        "avg_ccu": item.avg_ccu,
        # Measured first-party signals. Exports carry raw values — the
        # rounding applied in the UI is a display rule, not a data rule.
        "followers": item.followers,
        # ISO string, matching how this file already emits dates. A tz-aware
        # datetime object cannot be written to .xlsx at all — openpyxl raises.
        "followers_captured_at": (
            item.followers_captured_at.isoformat() if item.followers_captured_at else None
        ),
        "follower_delta_14d": item.follower_delta_14d,
        "wishlist_rank": item.wishlist_rank,
        "rank_delta_7d": item.rank_delta_7d,
        "wishlist": item.wishlist.value,
        "wishlist_comparator": item.wishlist.comparator,
        "wishlist_disclosed_on": (
            item.wishlist.disclosed_on.isoformat() if item.wishlist.disclosed_on else None
        ),
        "wishlist_status": item.wishlist.status,
        "wishlist_source": item.wishlist.source_name,
        "revenue_usd": item.revenue.value,
        "revenue_status": item.revenue.status,
        "revenue_source": item.revenue.source_name,
        "revenue_estimate_spread": item.revenue.estimate_spread,
        "estimated_sales": item.estimated_sales,
        "steam_url": item.steam_store_url,
        "steamdb_url": item.steamdb_url,
    }


def _to_markdown(df: pd.DataFrame) -> str:
    """Hand-rolled markdown table (no tabulate dependency)."""

    def cell(value) -> str:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return ""
        return str(value).replace("|", r"\|").replace("\n", " ")

    header = "| " + " | ".join(df.columns) + " |"
    divider = "| " + " | ".join("---" for _ in df.columns) + " |"
    rows = ["| " + " | ".join(cell(v) for v in row) + " |" for row in df.itertuples(index=False)]
    generated = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    intro = (
        "# Steam 2026 Indie Games Export\n\n"
        f"Generated {generated} — {len(df)} games. "
        "`followers` and `wishlist_rank` are MEASURED values Valve publishes. "
        "`wishlist_rank` is a position on Valve's Top-Wishlists chart, which "
        "blends total wishlists with recent velocity — it is not a count, and "
        "no count can be derived from it; empty means the game is not on the "
        "chart. `wishlist` is populated only where a developer disclosed a "
        "figure, and `wishlist_comparator` is `>=` when they stated a lower "
        "bound. Wishlist/revenue carry a status column: confirmed / estimated "
        "/ unknown (empty value = unknown, never a guess).\n\n"
    )
    return intro + "\n".join([header, divider, *rows]) + "\n"


def export_bytes(items: list[GameListItem], fmt: str) -> tuple[bytes, str]:
    """Returns (payload, filename)."""
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M")
    filename = f"steam2026-indie-games-{stamp}.{fmt}"

    if fmt == "json":
        payload = (
            "[" + ",".join(item.model_dump_json() for item in items) + "]"
        ).encode("utf-8")
        return payload, filename

    df = pd.DataFrame([_flatten(item) for item in items])

    if fmt == "csv":
        # utf-8-sig so Excel opens it with correct characters.
        return df.to_csv(index=False).encode("utf-8-sig"), filename
    if fmt == "xlsx":
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="games")
        return buffer.getvalue(), filename
    if fmt == "md":
        return _to_markdown(df).encode("utf-8"), filename

    raise ValueError(f"unsupported format: {fmt}")
