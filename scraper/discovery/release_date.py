"""Parse Steam's free-form release date strings.

Steam returns anything from "7 Aug, 2026" to "Q1 2026", "August 2026",
"2026", "Coming soon" or "To be announced". We keep the raw string and
extract what can be known for certain — never guess a more precise date
than the source provides.
"""

import datetime
import re
from dataclasses import dataclass

_FULL_DATE_FORMATS = ("%d %b, %Y", "%b %d, %Y", "%d %B, %Y", "%B %d, %Y")
_YEAR_RE = re.compile(r"\b(20\d{2})\b")


@dataclass(frozen=True)
class ParsedRelease:
    raw: str
    date: datetime.date | None  # exact day known
    year: int | None            # year known even if day is not


def parse_release(raw: str | None) -> ParsedRelease:
    text = (raw or "").strip()
    if not text:
        return ParsedRelease(raw="", date=None, year=None)

    for fmt in _FULL_DATE_FORMATS:
        try:
            parsed = datetime.datetime.strptime(text, fmt).date()
            return ParsedRelease(raw=text, date=parsed, year=parsed.year)
        except ValueError:
            continue

    match = _YEAR_RE.search(text)
    year = int(match.group(1)) if match else None
    return ParsedRelease(raw=text, date=None, year=year)
