"""Harvest developer-disclosed COPIES SOLD from official Steam news.

The revenue estimator's multipliers are borrowed from published research.
The only way to find out whether they hold for this catalogue is to compare
them against games whose developers said out loud how many copies they sold
— and developers do say it, in the same Steam announcements this project
already reads for wishlist milestones.

This is the twin of wishlist_disclosures.py and deliberately reuses its
scanning guards rather than restating them: goal-vs-achievement, historical
values quoted for contrast, deltas, ranks, "almost 200,000", round-number
lower bounds and the numeric parser are all identical problems, and every
one of those rules exists because of an observed failure. Only the noun
changes — and the noun is where this module has to be much stricter.

What it refuses to count, and why each one would corrupt a calibration:

  * "players", "downloads", "installs", "users", "owners" — free weekends,
    giveaways, Game Pass and gifted keys all inflate these well past copies
    sold. A multiplier fitted on player counts would be systematically too
    high.
  * cross-platform totals ("across all platforms", "on Switch and PC") —
    the multiplier maps Steam reviews to STEAM sales. A console-inclusive
    total silently attributes other storefronts' sales to Steam.
  * revenue figures — a dollar amount cannot be converted back to copies
    without knowing the average selling price, which is the very thing
    being estimated.

Rejections are returned rather than dropped, so the dry-run CSV can show a
human what was thrown away and why. A silent filter is indistinguishable
from a broken one.
"""

import datetime
import re
from dataclasses import dataclass

from scraper.collectors.wishlist_disclosures import (
    _APPROACHING_RE,
    _DELTA_RE,
    _HISTORICAL_RE,
    _NUMBER,
    _PREFIX_WINDOW,
    _RANK_RE,
    _TARGET_MARKERS,
    _LOWER_BOUND_RE,
    ROUND_BOUND_STEP,
    _excerpt,
    _sentence_around,
    _strip_tags,
    parse_amount,
)

# A solo indie selling fewer than 100 copies does not announce it; anything
# above 100 million is regex debris or a franchise-lifetime figure.
MIN_PLAUSIBLE = 100
MAX_PLAUSIBLE = 100_000_000

_SALES_NOUN = r"cop(?:y|ies)|units?"
_SOLD = r"sold|shifted"

# (pattern, the number is bound to an explicit copies/units noun).
# "sold 50,000 copies" / "50,000 copies sold" / "50K units sold" all name the
# unit next to the figure; "sales passed 30,000" does not, and only that
# third shape can be about the wrong thing.
_PATTERNS = [
    (
        re.compile(
            rf"\b(?:{_SOLD})\s+(?:over\s+|more than\s+)?{_NUMBER}\s*(?:{_SALES_NOUN})", re.I
        ),
        True,
    ),
    (re.compile(rf"{_NUMBER}\s*(?:{_SALES_NOUN})\s+(?:{_SOLD})", re.I), True),
    (
        re.compile(
            rf"\bsales\s*(?:have\s+)?(?:passed|surpassed|reached|hit)\s+{_NUMBER}", re.I
        ),
        False,
    ),
]

# Nouns that are NOT copies sold. Only consulted for the shape that does not
# name its unit: when the figure is written "40,123 copies sold", a mention
# of players elsewhere in the sentence does not make it ambiguous, and
# rejecting it would throw away a perfectly good data point.
_AMBIGUOUS_NOUN_RE = re.compile(
    r"\b(players?|downloads?|installs?|users?|owners?|wishlists?|followers?|"
    r"playtesters?|demo)\b",
    re.I,
)
_CROSS_PLATFORM_RE = re.compile(
    r"\b(all platforms|across platforms|every platform|combined|worldwide across|"
    r"switch|playstation|ps[45]\b|xbox|epic games store|itch\.io|gog|game pass)\b",
    re.I,
)

# Bound wording the pattern itself swallows: "sold over 12,345 copies".
_INLINE_BOUND_RE = re.compile(
    r"\b(?:over|more than|passed|surpassed|reached|hit)\b", re.I
)

REASON_AMBIGUOUS = "counts players/downloads, not copies sold"
REASON_CROSS_PLATFORM = "not Steam-only"
REASON_IMPLAUSIBLE = "outside the plausible range"
REASON_TARGET = "a goal, not an achievement"
REASON_CONTEXT = "historical value, delta or rank"
REASON_BELOW = "describes a value below the figure"


@dataclass(frozen=True)
class SalesDisclosure:
    appid: int
    copies: int
    comparator: str          # '=' | '>='
    disclosed_on: datetime.date
    title: str
    url: str
    excerpt: str


@dataclass(frozen=True)
class RejectedMention:
    """A number that matched the shape but failed a rule.

    Carried out of the parser so the review CSV can show it. Most of these
    are correct rejections; the ones that are not are how the rules get
    fixed.
    """

    appid: int
    value: int
    reason: str
    excerpt: str
    url: str


def find_sales_disclosures(
    appid: int, news_items: list[dict]
) -> tuple[list[SalesDisclosure], list[RejectedMention]]:
    """Pure over the raw news items — unit-testable with no network."""
    found: list[SalesDisclosure] = []
    rejected: list[RejectedMention] = []
    seen_values: set[int] = set()

    # Oldest first, so the first announcement of a milestone wins and later
    # restatements are the ones dropped.
    for item in sorted(news_items, key=lambda i: int(i.get("date") or 0)):
        corpus = _strip_tags(f"{item.get('title', '')}. {item.get('contents', '')}")
        epoch = int(item.get("date") or 0)
        if not epoch:
            continue
        disclosed_on = datetime.datetime.fromtimestamp(
            epoch, tz=datetime.timezone.utc
        ).date()
        url = item.get("url", "")

        for pattern, names_its_unit in _PATTERNS:
            for match in pattern.finditer(corpus):
                raw, suffix = match.group(1), match.group(2)
                value = parse_amount(raw, suffix)
                if value is None:
                    continue
                sentence = _sentence_around(corpus, match.start(), match.end())
                excerpt = _excerpt(corpus, match.start(), match.end())

                def reject(reason: str) -> None:
                    rejected.append(
                        RejectedMention(appid, value, reason, excerpt, url)
                    )

                if not (MIN_PLAUSIBLE <= value <= MAX_PLAUSIBLE):
                    reject(REASON_IMPLAUSIBLE)
                    continue
                if not names_its_unit and _AMBIGUOUS_NOUN_RE.search(sentence):
                    reject(REASON_AMBIGUOUS)
                    continue
                if _CROSS_PLATFORM_RE.search(sentence):
                    reject(REASON_CROSS_PLATFORM)
                    continue
                if any(marker in sentence.lower() for marker in _TARGET_MARKERS):
                    reject(REASON_TARGET)
                    continue

                prefix = corpus[max(0, match.start() - _PREFIX_WINDOW):match.start()]
                if (
                    _HISTORICAL_RE.search(prefix)
                    or _DELTA_RE.search(prefix)
                    or _RANK_RE.search(prefix)
                ):
                    reject(REASON_CONTEXT)
                    continue
                if _APPROACHING_RE.search(prefix):
                    reject(REASON_BELOW)
                    continue
                if value in seen_values:
                    continue  # restatement of a milestone already recorded

                # Same rule as wishlists: round milestones are what people
                # announce when they pass a number, not exact telemetry.
                # "sold over 12,345 copies" carries its bound INSIDE the
                # match, so the prefix alone would miss it.
                explicit_bound = bool(_LOWER_BOUND_RE.search(prefix)) or bool(
                    _INLINE_BOUND_RE.search(match.group(0))
                )
                round_number = value % ROUND_BOUND_STEP == 0
                seen_values.add(value)
                found.append(
                    SalesDisclosure(
                        appid=appid,
                        copies=value,
                        comparator=">=" if (explicit_bound or round_number) else "=",
                        disclosed_on=disclosed_on,
                        title=item.get("title", "")[:200],
                        url=url,
                        excerpt=excerpt,
                    )
                )
    return found, rejected
