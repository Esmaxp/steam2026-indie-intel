"""Multi-signal indie confidence scoring (promt.md Section 1).

The Steam "Indie" genre remains the mandatory base filter (applied in the
store collector). This module refines it:

- publisher on the known AAA/AA list      → confidence LOW, is_indie False
  (flagged for review — never auto-deleted)
- self-published (developer == publisher) → confidence HIGH
- boutique indie label (Devolver-scale)   → confidence MEDIUM (real indie
  games, but a sizable label is involved)
- anything else                           → confidence MEDIUM
"""

import re
from dataclasses import dataclass

from app.models import IndieConfidence

# Large AAA/AA publishers. Matching is on normalized names; substring match is
# used so "Ubisoft Entertainment" and "Ubisoft Montréal" both hit "ubisoft".
MAJOR_PUBLISHERS = (
    "electronic arts", "ea games", "ubisoft", "take-two", "take two", "2k games",
    "2k ", "rockstar games", "tencent", "level infinite", "sony interactive",
    "playstation", "microsoft", "xbox game studios", "activision", "blizzard",
    "nintendo", "square enix", "bandai namco", "sega", "capcom", "konami",
    "embracer", "thq nordic", "deep silver", "plaion", "warner bros",
    "wb games", "epic games", "krafton", "netease", "hoyoverse", "mihoyo",
    "paradox interactive", "focus entertainment", "nacon", "505 games",
    "cd projekt", "bethesda", "zenimax", "riot games", "gearbox publishing",
    "private division", "amazon games", "netmarble", "my.games", "gameloft",
)

# Sizable-but-indie labels ("Devolver-scale"): games stay indie, but
# self-published-level confidence would overstate it.
BOUTIQUE_LABELS = (
    "devolver digital", "annapurna interactive", "raw fury", "team17",
    "tinybuild", "curve games", "curve digital", "coffee stain",
    "humble games", "finji", "panic", "fellow traveller", "no more robots",
    "chucklefish", "playdigious", "hooded horse", "kepler interactive",
    "secret mode", "daedalic", "dear villagers", "playstack", "hypetrain",
)

_SUFFIX_RE = re.compile(
    r"\b(ltd|llc|inc|co|corp|gmbh|s\.?a\.?|sp\.? z o\.?o\.?|studio[s]?|"
    r"games|entertainment|interactive|software|publishing)\b\.?",
)


def normalize_company(name: str) -> str:
    """Lowercase, strip punctuation and legal/common suffixes."""
    text = name.casefold().replace(",", " ").replace(".", " ")
    text = re.sub(r"[^\w\s-]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _core_name(name: str) -> str:
    """Normalized name with generic suffix words removed (for == comparison)."""
    return re.sub(r"\s+", " ", _SUFFIX_RE.sub(" ", normalize_company(name))).strip()


def _match_list(publishers: list[str], candidates: tuple[str, ...]) -> str | None:
    for publisher in publishers:
        normalized = normalize_company(publisher)
        for candidate in candidates:
            if candidate.strip() in normalized:
                return publisher
    return None


@dataclass(frozen=True)
class IndieSignal:
    confidence: IndieConfidence
    is_indie: bool
    reason: str


def score_indie_signals(developers: list[str], publishers: list[str]) -> IndieSignal:
    """Assumes the Steam Indie genre check (base filter) already passed."""
    major = _match_list(publishers, MAJOR_PUBLISHERS)
    if major:
        return IndieSignal(
            confidence=IndieConfidence.LOW,
            is_indie=False,
            reason=f"publisher '{major}' matches the known AAA/AA list",
        )

    dev_cores = {_core_name(d) for d in developers if d.strip()}
    pub_cores = {_core_name(p) for p in publishers if p.strip()}
    if not pub_cores or (dev_cores and dev_cores & pub_cores):
        return IndieSignal(
            confidence=IndieConfidence.HIGH,
            is_indie=True,
            reason="self-published (developer == publisher)",
        )

    boutique = _match_list(publishers, BOUTIQUE_LABELS)
    if boutique:
        return IndieSignal(
            confidence=IndieConfidence.MEDIUM,
            is_indie=True,
            reason=f"boutique indie label '{boutique}'",
        )

    return IndieSignal(
        confidence=IndieConfidence.MEDIUM,
        is_indie=True,
        reason="third-party publisher, not on any known-large list",
    )
