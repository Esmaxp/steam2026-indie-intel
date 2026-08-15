"""Axis 1 — how much production effort a store page evidences (0-100).

This answers "did someone build this like a product?", NOT "did it sell?".
Conflating the two is what makes market analyses discard the games this
catalogue exists to surface: a developer who spent three years on a game and
then failed at marketing looks identical to an asset flip if you only count
reviews. Sales, reviews, followers, wishlist rank and CCU are therefore not
inputs here — see app.services.traction_score for those.

Every signal below is something a developer *chooses to do* before any player
reacts, and each one carries its own rationale in SIGNAL_DOC: what it measures,
why it is relevant, how it is measured from our data, its strength, and the
false positives it can produce. Weights are not intuition — the first cut of
this module rewarded having a trailer (+2) until a 400-game random sample
showed 94.8% of the catalogue has one, which handed almost everything a free
pass. Prevalence figures below come from that sample and from the full
catalogue for the columns we already had.

Nothing here is definitive on its own; that is the design. A cheap price, a
missing website, an AI disclosure or a low review count each mean very little
alone, which is why no single signal can move a game across a class boundary
by itself.
"""

from dataclasses import dataclass, field

# --- thresholds, all set from the catalogue's own distribution --------------
PRICE_SERIOUS_CENTS = 800    # 16.7% of the catalogue lists at or above $8
PRICE_MINIMUM_CENTS = 300    # 15.3% of paid games list below $3
SCREENSHOT_BAR = 10          # top quartile; 99.8% clear 5, so 5 says nothing
LANGUAGE_BAR = 3             # 43.5%
LANGUAGE_DEEP_BAR = 6        # 31.9%
DESCRIPTION_BAR = 228        # catalogue median length
DESCRIPTION_FLOOR = 100      # bottom 5.4%: the field was barely filled in
DEVELOPER_VELOCITY_BAR = 3   # releases in the catalogue year

# Best case if a developer does everything observable. The raw sum is scaled
# against this, so the published score is a percentage of "fully productised".
MAX_POSITIVE = 110

SERIOUS_AT = 55
MIXED_AT = 30

CLASS_SERIOUS = "serious"
CLASS_MIXED = "mixed"
CLASS_HOBBY = "hobby"
CLASS_UNKNOWN = "unknown"

# name → (points, what it measures, why it matters, strength, failure mode)
SIGNAL_DOC: dict[str, tuple[int, str, str, str, str]] = {
    "screenshots": (
        10,
        "at least 10 store screenshots",
        "shots have to be staged and picked; a bulk upload ships the minimum",
        "medium",
        "an asset-flip can screenshot 20 rooms of a template project",
    ),
    "localised": (
        8,
        "3 or more supported languages",
        "localisation costs money or time and implies an audience plan",
        "medium",
        "engine-generated machine translation is cheap for text-light games",
    ),
    "localised_deep": (
        6,
        "6 or more supported languages (on top of the above)",
        "at this depth it is a deliberate publishing decision, not a checkbox",
        "medium",
        "same machine-translation caveat",
    ),
    "website": (
        12,
        "an official website is listed on the store page",
        "somebody registered a domain and maintains a page for this game",
        "medium",
        "a studio's shared site counts for every game it ships",
    ),
    "demo": (
        14,
        "a playable demo is published",
        "a demo is a separate build, separately QA'd — rare for throwaway work",
        "strong",
        "demo-only 'games' exist as marketing shells for unreleased projects",
    ),
    "achievements": (
        10,
        "the game defines Steam achievements",
        "achievements are authored per game and require Steamworks integration",
        "medium",
        "card-farming shovelware sometimes adds trivial achievements on purpose",
    ),
    "next_fest": (
        12,
        "participated in a Steam Next Fest",
        "a scheduled event with an application and a demo requirement",
        "strong",
        "none material — participation is gated by Valve",
    ),
    "social_channels": (
        8,
        "an official YouTube/Twitch/Discord channel is known for the game",
        "sustained community work beyond shipping the build",
        "weak",
        "our channel data only covers games whose website we scanned, so an "
        "absent channel proves nothing — this signal only ever adds",
    ),
    "price_positioned": (
        20,
        "list price at or above $8",
        "pricing like a product implies expecting to be judged as one",
        "strong",
        "a hobby project can be overpriced; premium pricing is not quality",
    ),
    "price_modest": (
        10,
        "list price between $3 and $8",
        "a real but modest commercial position",
        "weak",
        "many serious small games deliberately price low",
    ),
    "description": (
        10,
        "store description at least at the catalogue median length",
        "writing copy is the cheapest possible effort; skipping it is telling",
        "weak",
        "a terse description can be a style choice",
    ),
    # --- negative signals --------------------------------------------------
    "no_trailer": (
        -15,
        "no trailer or gameplay video on the store page",
        "94.8% of the catalogue has one; not cutting one is the outlier",
        "medium",
        "our own parser was broken for months — never score this without a "
        "successful store-page read (see store_data_seen)",
    ),
    "price_below_floor": (
        -15,
        "paid game listed under $3",
        "the classic positioning of card-farming and bulk uploads",
        "medium",
        "legitimate micro-games and student projects price this low too",
    ),
    "thin_description": (
        -8,
        "store description under 100 characters",
        "bottom 5% — effectively an unfilled field",
        "weak",
        "non-English pages sometimes carry a very short blurb",
    ),
    "mass_published": (
        -25,
        "the developer or publisher shipped 5+ games within 30 days",
        "describes a volume operation rather than a project",
        "strong",
        "a publisher's burst flags every game it ever released, including good "
        "ones — this is the single most likely source of a wrong 'hobby'",
    ),
    "developer_volume": (
        -15,
        "the developer has more than 3 releases in the catalogue year",
        "a normal indie cycle is one to three years per game",
        "medium",
        "prolific micro-game developers and porting houses are misread here",
    ),
}


@dataclass(frozen=True)
class EffortInput:
    """Everything the score reads. No traction metric appears here, by design."""

    has_trailer: bool
    screenshot_count: int
    list_price_cents: int | None
    is_free: bool
    language_count: int
    has_website: bool
    demo_available: bool
    achievements_count: int | None
    description_length: int
    next_fest: bool
    has_social_channels: bool
    mass_published: bool
    developer_releases: int
    # False when the store page could not be read: the difference between
    # "no signals" and "we never looked".
    store_data_seen: bool = True


@dataclass(frozen=True)
class EffortResult:
    score: int                 # 0-100
    effort_class: str
    raw: int
    observed: int              # how many signals could be evaluated
    signals: dict[str, int] = field(default_factory=dict)


def score(data: EffortInput) -> EffortResult:
    """Sum the signals that fired, scale to 0-100, and keep the breakdown."""
    if not data.store_data_seen:
        return EffortResult(score=0, effort_class=CLASS_UNKNOWN, raw=0, observed=0)

    signals: dict[str, int] = {}

    def fire(name: str) -> None:
        signals[name] = SIGNAL_DOC[name][0]

    if not data.has_trailer:
        fire("no_trailer")
    if data.screenshot_count >= SCREENSHOT_BAR:
        fire("screenshots")
    if data.language_count >= LANGUAGE_BAR:
        fire("localised")
    if data.language_count >= LANGUAGE_DEEP_BAR:
        fire("localised_deep")
    if data.has_website:
        fire("website")
    if data.demo_available:
        fire("demo")
    if data.achievements_count:
        fire("achievements")
    if data.next_fest:
        fire("next_fest")
    if data.has_social_channels:
        fire("social_channels")

    # Free-to-play is a business model, not an absence of effort, so free games
    # are exempt from pricing signals entirely rather than scored at zero.
    if not data.is_free and data.list_price_cents is not None:
        if data.list_price_cents >= PRICE_SERIOUS_CENTS:
            fire("price_positioned")
        elif data.list_price_cents >= PRICE_MINIMUM_CENTS:
            fire("price_modest")
        else:
            fire("price_below_floor")

    if data.description_length >= DESCRIPTION_BAR:
        fire("description")
    elif data.description_length < DESCRIPTION_FLOOR:
        fire("thin_description")

    if data.mass_published:
        fire("mass_published")
    if data.developer_releases > DEVELOPER_VELOCITY_BAR:
        fire("developer_volume")

    raw = sum(signals.values())
    scaled = max(0, min(100, round(100 * raw / MAX_POSITIVE)))
    if scaled >= SERIOUS_AT:
        effort_class = CLASS_SERIOUS
    elif scaled >= MIXED_AT:
        effort_class = CLASS_MIXED
    else:
        effort_class = CLASS_HOBBY
    return EffortResult(
        score=scaled,
        effort_class=effort_class,
        raw=raw,
        observed=len(signals),
        signals=signals,
    )
