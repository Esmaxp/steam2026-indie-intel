"""Harvest developer-disclosed wishlist counts from official Steam news.

Steam publishes no wishlist numbers, so the ONLY route to a confirmed figure
is a developer stating one publicly. They routinely do, in their own Steam
announcements ("we just passed 50,000 wishlists!"), and Valve's own
ISteamNews API serves those posts — making this a first-party source for a
first-party-only project.

Every extraction rule below exists because of a specific observed failure.
They look fussy; each one is load-bearing:

  * TARGET markers ("all the way to 1,000,000 wishlists!") are promotional
    goals, not achievements. One such figure was the single largest data
    point in an earlier analysis and skewed it badly.
  * A hard ceiling kills regex debris: one post yielded 9,073,139,032,455
    from a mangled "…539073139032455 Wishlist".
  * Digits are grouped with commas, dots, spaces or thin spaces depending on
    locale, and K/M suffixes are common. "500 000" silently parsed as 000
    before this handled spaces.
  * A bare 4-digit number in the 2019-2030 range is nearly always a year.
  * Developers restate milestones ("still at 400,000!"), so a repeat of a
    figure already recorded for that game is dropped.
  * ~85% of disclosures are round-number LOWER BOUNDS. Recording "over
    100,000" as an exact 100,000 would overstate what was actually said, so
    comparator carries '>=' — explicitly when the wording says so, and by
    default for any suspiciously round multiple of 5,000.

Output is CONFIRMED-status rows, which is the highest trust tier in this
codebase. The harvester therefore defaults to --dry-run: a human decides
what gets promoted to confirmed, exactly as disclosed_numbers_source.py
requires today.
"""

import datetime
import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Cap: anything larger is regex debris, not a wishlist count. The most
# wishlisted game on Steam has ~5M.
MAX_PLAUSIBLE = 50_000_000
MIN_PLAUSIBLE = 100

# Round numbers are how people report milestones they have passed, not exact
# telemetry. Treat any multiple of this as a lower bound unless stated otherwise.
ROUND_BOUND_STEP = 5_000

# Digits grouped by comma, dot, space or NBSP/thin space, optional K/M suffix.
_NUMBER = r"(\d[\d.,    ]*\d|\d)\s*([KkMm])?"
_WISHLIST_WORD = r"wish\s*-?\s*list(?:s|ed)?"

# "50,000 wishlists" / "125.4K wishlists"
# The reversed form REQUIRES a separator ("wishlists: 40 000"). Without one,
# "wishlisted 1348 Ex Voto" — a number inside the game's own title — parsed
# as a wishlist count. "wishlisted N" means "added N to a wishlist", which is
# never the total.
_PATTERNS = [
    re.compile(rf"{_NUMBER}\s*(?:\+\s*)?{_WISHLIST_WORD}", re.I),
    re.compile(rf"wish\s*-?\s*lists?\s*[:\-–]\s*{_NUMBER}", re.I),
]

# Text immediately BEFORE the figure that changes what it means.
# "climb from 1,700 wishlists to this high" — a historical value being
# contrasted with the current one.
# The approximator is optional and may be a tilde: "started at ~10 000".
_APPROX = r"[~≈]?\s*(?:about|around|approximately|roughly)?\s*"
_HISTORICAL_RE = re.compile(
    rf"\b(?:from|was|were|started (?:at|with)|had|began (?:at|with))\s*{_APPROX}$", re.I
)
# "we've gained 2500 wishlists in two weeks" / "the +2,000 wishlists" — a
# delta or rate, not a total.
_DELTA_RE = re.compile(
    r"(?:\b(?:gained|added|picked up|grew by|up by|earned|got|another|extra|"
    r"plus|averaging|gaining|adding)\b[^.]{0,20}|\+\s*)$",
    re.I,
)
# "crack the top 1000 wishlisted games" is a RANK, not a count.
_RANK_RE = re.compile(r"\b(?:top|rank(?:ed|ing)?|position|number|no\.?|#)\s*$", re.I)
# "almost 200,000" / "approaching 25,000" / "just shy of a 1000" describe a
# value BELOW the figure. The schema can express '=' and '>=' only, so
# recording these at all would misstate them — reject instead of inverting.
# The verb may sit between the qualifier and the figure: "almost REACHED
# 200 000 wishlists" still describes a value below 200,000.
_APPROACHING_RE = re.compile(
    r"\b(?:almost|nearly|approaching|close to|just shy of|shy of|under|below|"
    r"less than|up to|toward|towards)\s+"
    r"(?:reached|reaching|hit|hitting|at|to|got to|crossed|there|a)?\s*{}$".format(_APPROX),
    re.I,
)
_PREFIX_WINDOW = 48

# Promotional goals, not achievements.
_TARGET_MARKERS = (
    "all the way to", "when we reach", "when we hit", "if we reach", "if we hit",
    "help us reach", "help us hit", "goal", "target", "unlock", "milestone at",
    "discount", "stretch", "let's get", "lets get", "can we", "aiming for",
    "on our way to", "next up", "road to",
    # Conditional/future phrasing: "will be back once Nadir achieves its 50k
    # wishlist milestone" is a promise, not an achievement.
    # NB: "hits" is deliberately NOT here. Headline style uses it in the past
    # sense ("Romestead Hits 250k Wishlists"), and excluding it dropped a
    # real disclosure.
    "once ", "achieves", "will reach", "we reach ",
)
# Explicit lower-bound wording, matched against the text immediately BEFORE
# the figure. Scanning the whole sentence produced false bounds: "…climb from
# 1,700 to this high over the course of a single week" made an exact figure
# read as ">=" because of an unrelated "over".
_LOWER_BOUND_RE = re.compile(
    r"\b(?:over|more than|surpassed|passed|beyond|north of|exceeded|above|"
    r"crossed|smashed|broke|reached|hit|collected|accumulated|celebrating|"
    r"thank(?:s)? (?:you )?for)\s+"
    r"(?:the\s+)?{}$".format(_APPROX),
    re.I,
)

_YEAR_RE = re.compile(r"^(19|20)\d{2}$")


@dataclass(frozen=True)
class Disclosure:
    appid: int
    wishlists: int
    comparator: str          # '=' | '>='
    disclosed_on: datetime.date
    title: str
    url: str
    excerpt: str


def _strip_tags(text: str) -> str:
    text = re.sub(r"\[/?[^\]]{1,40}\]", " ", text)      # Steam BBCode
    text = re.sub(r"<[^>]{1,200}>", " ", text)          # stray HTML
    return re.sub(r"\s+", " ", text)


def parse_amount(raw: str, suffix: str | None) -> int | None:
    """'125.4' + 'K' -> 125400; '500 000' -> 500000; '1,234' -> 1234."""
    cleaned = raw.replace(" ", "").replace(" ", "").replace(" ", "")
    cleaned = cleaned.replace(" ", "")
    if suffix:
        # With a K/M suffix a dot is a decimal point, not a separator.
        cleaned = cleaned.replace(",", ".")
        try:
            value = float(cleaned)
        except ValueError:
            return None
        value *= 1_000 if suffix.lower() == "k" else 1_000_000
        return int(round(value))
    # No suffix: commas and dots are thousands separators.
    if _YEAR_RE.match(cleaned):
        return None  # bare 4-digit year
    digits = cleaned.replace(",", "").replace(".", "")
    if not digits.isdigit():
        return None
    return int(digits)


def _sentence_around(text: str, start: int, end: int) -> str:
    left = max(text.rfind(".", 0, start), text.rfind("!", 0, start),
               text.rfind("\n", 0, start)) + 1
    right_candidates = [p for p in (text.find(".", end), text.find("!", end),
                                    text.find("\n", end)) if p != -1]
    right = min(right_candidates) if right_candidates else len(text)
    return text[left:right].strip()


def _excerpt(text: str, start: int, end: int, width: int = 150) -> str:
    """A window that ALWAYS contains the matched figure.

    The sentence alone is not enough: a long run-on sentence truncated to a
    fixed length can omit the very number under review, which makes the
    dry-run CSV unauditable — the one thing it exists for.
    """
    sentence = _sentence_around(text, start, end)
    if len(sentence) <= width:
        return sentence
    left = max(0, start - width // 2)
    return ("…" if left else "") + text[left:left + width].strip() + "…"


def find_wishlist_disclosures(appid: int, news_items: list[dict]) -> list[Disclosure]:
    """Pure over the raw news items — unit-testable with no network."""
    found: list[Disclosure] = []
    seen_values: set[int] = set()

    # Oldest first, so the FIRST time a milestone is announced wins and later
    # restatements are the ones dropped.
    for item in sorted(news_items, key=lambda i: int(i.get("date") or 0)):
        corpus = _strip_tags(f"{item.get('title', '')}. {item.get('contents', '')}")
        epoch = int(item.get("date") or 0)
        if not epoch:
            continue
        disclosed_on = datetime.datetime.fromtimestamp(
            epoch, tz=datetime.timezone.utc
        ).date()

        for pattern in _PATTERNS:
            for match in pattern.finditer(corpus):
                raw, suffix = match.group(1), match.group(2)
                value = parse_amount(raw, suffix)
                if value is None or not (MIN_PLAUSIBLE <= value <= MAX_PLAUSIBLE):
                    continue

                sentence = _sentence_around(corpus, match.start(), match.end())
                low = sentence.lower()
                if any(marker in low for marker in _TARGET_MARKERS):
                    continue  # a goal, not an achievement

                # Checked against the text immediately before the figure
                # rather than the whole sentence: a growth narrative often
                # contains BOTH a historical value and the real current one.
                prefix = corpus[max(0, match.start() - _PREFIX_WINDOW):match.start()]
                if _HISTORICAL_RE.search(prefix):
                    continue  # a past value quoted for contrast
                if _DELTA_RE.search(prefix):
                    continue  # a change over time, not a total
                if _RANK_RE.search(prefix):
                    continue  # a chart position, not a count
                if _APPROACHING_RE.search(prefix):
                    continue  # describes a value below the figure
                if value in seen_values:
                    continue  # restatement of a milestone already recorded

                explicit_bound = bool(_LOWER_BOUND_RE.search(prefix))
                round_number = value % ROUND_BOUND_STEP == 0
                comparator = ">=" if (explicit_bound or round_number) else "="

                seen_values.add(value)
                found.append(
                    Disclosure(
                        appid=appid,
                        wishlists=value,
                        comparator=comparator,
                        disclosed_on=disclosed_on,
                        title=item.get("title", "")[:200],
                        url=item.get("url", ""),
                        excerpt=_excerpt(corpus, match.start(), match.end()),
                    )
                )
    return found
