"""Rule-based game classification from public Steam signals.

Inputs: store tags (vote-ordered), store description text, legal notice.
Every dimension defaults to *unknown* — a value is only assigned when a
clear signal exists. Nothing is guessed.
"""

import re
from dataclasses import dataclass

from app.models import Camera, Dimension, GameEngine, GraphicsStyle

# --- tag maps (case-insensitive tag name → enum) ---------------------------

_DIMENSION_TAGS = {
    "2d": Dimension.TWO_D,
    "2.5d": Dimension.TWO_HALF_D,
    "3d": Dimension.THREE_D,
}

_CAMERA_TAGS = {
    "top-down": Camera.TOP_DOWN,
    "top down": Camera.TOP_DOWN,
    "isometric": Camera.ISOMETRIC,
    "first-person": Camera.FIRST_PERSON,
    "first person": Camera.FIRST_PERSON,
    "third person": Camera.THIRD_PERSON,
    "third-person": Camera.THIRD_PERSON,
    "side scroller": Camera.SIDE_SCROLLER,
}

_GRAPHICS_TAGS = {
    "pixel graphics": GraphicsStyle.PIXEL_ART,
    "voxel": GraphicsStyle.VOXEL,
    "anime": GraphicsStyle.ANIME,
    "realistic": GraphicsStyle.REALISTIC,
    "stylized": GraphicsStyle.STYLIZED,
    "hand-drawn": GraphicsStyle.HAND_PAINTED,
}

# --- description regexes (more specific than tags, checked as refinement) --

_GRAPHICS_DESC_PATTERNS = (
    (re.compile(r"\bhd[- ]?pixel[- ]?art\b", re.I), GraphicsStyle.HD_PIXEL_ART),
    (re.compile(r"\b(ps1|psx|playstation 1)[- ]?(style|era|inspired|graphics|aesthetic)", re.I),
     GraphicsStyle.PS1_STYLE),
    (re.compile(r"\b(ps2|playstation 2)[- ]?(style|era|inspired|graphics|aesthetic)", re.I),
     GraphicsStyle.PS2_STYLE),
    (re.compile(r"\blow[- ]?poly\b", re.I), GraphicsStyle.LOW_POLY),
    (re.compile(r"\bhand[- ]?(painted|drawn)\b", re.I), GraphicsStyle.HAND_PAINTED),
)

_ENGINE_PATTERNS = (
    (re.compile(r"unreal\s*(?:®|\(r\))?\s*engine|epic games tools", re.I), GameEngine.UNREAL),
    (re.compile(r"made with unity|unity\s+(?:engine|technologies)|unity\s*®", re.I),
     GameEngine.UNITY),
    (re.compile(r"\bgodot\b", re.I), GameEngine.GODOT),
    (re.compile(r"game\s*maker(?:\s*studio)?|\bgamemaker\b|yoyo\s*games", re.I),
     GameEngine.GAMEMAKER),
    (re.compile(r"(custom|in[- ]house|proprietary)[- ](game\s+)?engine", re.I),
     GameEngine.CUSTOM),
)


@dataclass(frozen=True)
class Classification:
    dimension: Dimension
    camera: Camera
    graphics_style: GraphicsStyle
    engine: GameEngine


def _best_tag_match(tags: list[tuple[str, int]], mapping: dict):
    """Highest-vote tag that appears in the mapping; None when absent."""
    best_value, best_votes = None, -1
    for name, votes in tags:
        mapped = mapping.get(name.strip().lower())
        if mapped is not None and votes > best_votes:
            best_value, best_votes = mapped, votes
    return best_value


def classify(
    tags: list[tuple[str, int]],
    description: str = "",
    legal_notice: str = "",
) -> Classification:
    """tags: (name, votes) pairs from the store page tag list."""
    dimension = _best_tag_match(tags, _DIMENSION_TAGS) or Dimension.UNKNOWN
    camera = _best_tag_match(tags, _CAMERA_TAGS) or Camera.UNKNOWN

    graphics = _best_tag_match(tags, _GRAPHICS_TAGS)
    # Description can be more specific (HD pixel art, PS1-style, low poly)
    # but only refines when tags gave nothing or the generic pixel/stylized hit.
    for pattern, style in _GRAPHICS_DESC_PATTERNS:
        if pattern.search(description):
            if graphics is None or (
                style is GraphicsStyle.HD_PIXEL_ART
                and graphics is GraphicsStyle.PIXEL_ART
            ):
                graphics = style
            break
    graphics = graphics or GraphicsStyle.UNKNOWN

    engine = GameEngine.UNKNOWN
    engine_corpus = f"{legal_notice}\n{description}"
    for pattern, candidate in _ENGINE_PATTERNS:
        if pattern.search(engine_corpus):
            engine = candidate
            break

    return Classification(
        dimension=dimension, camera=camera, graphics_style=graphics, engine=engine
    )
