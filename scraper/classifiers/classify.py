"""Rule-based game classification from public Steam signals.

Inputs: store tags (vote-ordered), store description text, legal notice.
Every dimension defaults to *unknown* — a value is only assigned when a
clear signal exists. Nothing is guessed.
"""

import re
from dataclasses import dataclass
from typing import Literal

from app.models import Camera, Dimension, GameEngine, GraphicsStyle

# A runner-up tag with at least this share of the winner's votes counts as a
# real disagreement rather than noise (see _best_tag_match).
CONFLICT_RATIO = 0.5

# --- tag maps (case-insensitive tag name → enum) ---------------------------

# Compound tag names are listed explicitly because matching is exact: only
# tags that *state* the value are mapped, never ones that merely suggest it.
# Deliberately absent: "retro" (splits between pixel art, PS1-style 3D and a
# retro theme), "arena shooter" (both first-person and twin-stick arenas),
# "puzzle platformer" (3D ones are common), "precision platformer" and
# "twin stick shooter" (~90% safe — held back pending a first-pass review).
_DIMENSION_TAGS = {
    "2d": Dimension.TWO_D,
    "2.5d": Dimension.TWO_HALF_D,
    "3d": Dimension.THREE_D,
    "2d platformer": Dimension.TWO_D,
    "3d platformer": Dimension.THREE_D,
}

_CAMERA_TAGS = {
    "top-down": Camera.TOP_DOWN,
    "top down": Camera.TOP_DOWN,
    "top-down shooter": Camera.TOP_DOWN,
    "isometric": Camera.ISOMETRIC,
    "first-person": Camera.FIRST_PERSON,
    "first person": Camera.FIRST_PERSON,
    "fps": Camera.FIRST_PERSON,  # the acronym is "first-person shooter"
    "boomer shooter": Camera.FIRST_PERSON,  # definitionally a retro FPS
    "third person": Camera.THIRD_PERSON,
    "third-person": Camera.THIRD_PERSON,
    "third-person shooter": Camera.THIRD_PERSON,
    "side scroller": Camera.SIDE_SCROLLER,
    "2d platformer": Camera.SIDE_SCROLLER,  # 2D + platformer leaves only side view
}

# "Cartoony"/"Cartoon" map to STYLIZED: there is no CARTOON member, stylized is
# the superset Steam's own "Stylized" tag already maps to, and it appears in no
# branch of _infer_dimension so it cannot contaminate the 2D/3D inference.
_GRAPHICS_TAGS = {
    "pixel graphics": GraphicsStyle.PIXEL_ART,
    "voxel": GraphicsStyle.VOXEL,
    "anime": GraphicsStyle.ANIME,
    "realistic": GraphicsStyle.REALISTIC,
    "stylized": GraphicsStyle.STYLIZED,
    "cartoony": GraphicsStyle.STYLIZED,
    "cartoon": GraphicsStyle.STYLIZED,
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

# Self-declared dimension in store copy — the least structured signal, only
# consulted when tags, camera, and graphics all left dimension unknown.
_DIMENSION_DESC_PATTERNS = (
    (re.compile(r"\bfully[- ](?:rendered )?3d\b", re.I), Dimension.THREE_D),
    (re.compile(r"\b3d\b", re.I), Dimension.THREE_D),
    (re.compile(r"\b2d\b", re.I), Dimension.TWO_D),
    (re.compile(r"\bside[- ]scroll(?:ing|er)\b", re.I), Dimension.TWO_D),
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
    # Auditability, same idea as games.discovery_method: "tag" = the store's
    # own 2d/2.5d/3d tag matched; "rule_based" = inferred from camera/graphics/
    # description; "unknown" = no signal (dimension stays UNKNOWN). The vision
    # worker writes "vision_ai" directly at the DB level.
    dimension_source: Literal["tag", "rule_based", "unknown"] = "unknown"


def _best_tag_match(tags: list[tuple[str, int]], mapping: dict):
    """Highest-vote tag that appears in the mapping; None when absent.

    Returns None as well when two tags map to *different* values and the
    runner-up is close enough to be credible — a game tagged both "3D" and
    "2D Platformer" has genuinely conflicting evidence. Same rule as
    _infer_dimension: signals disagree, so nothing is claimed. A landslide
    (the runner-up below CONFLICT_RATIO of the winner) is treated as noise,
    which is the common case for a stray tag on a heavily-voted page.
    """
    votes_by_value: dict = {}
    for name, votes in tags:
        mapped = mapping.get(name.strip().lower())
        if mapped is not None:
            votes_by_value[mapped] = max(votes_by_value.get(mapped, -1), votes)
    if not votes_by_value:
        return None

    ranked = sorted(votes_by_value.items(), key=lambda item: item[1], reverse=True)
    best_value, best_votes = ranked[0]
    if len(ranked) > 1 and ranked[1][1] >= best_votes * CONFLICT_RATIO:
        return None
    return best_value


def _infer_dimension(camera: Camera, graphics: GraphicsStyle, description: str) -> Dimension:
    """Rule-based fallback when the store's own 2d/2.5d/3d tag is missing.

    Reuses the camera and graphics signals already computed by classify().
    Conflicting signals (e.g. a 3D low-poly side-scroller) stay UNKNOWN —
    nothing is guessed. Description regexes are the last resort and only run
    when camera and graphics gave no signal at all.
    """
    votes: set[Dimension] = set()

    # A first/third-person camera is essentially never 2D.
    if camera in (Camera.FIRST_PERSON, Camera.THIRD_PERSON):
        votes.add(Dimension.THREE_D)
    elif camera is Camera.SIDE_SCROLLER:
        # Side-scrollers are virtually always 2D/2.5D sprite-based.
        votes.add(Dimension.TWO_D)

    if graphics in (
        GraphicsStyle.VOXEL,
        GraphicsStyle.LOW_POLY,
        GraphicsStyle.PS1_STYLE,
        GraphicsStyle.PS2_STYLE,
    ):
        # These styles are inherently 3D-rendered.
        votes.add(Dimension.THREE_D)
    elif graphics in (GraphicsStyle.PIXEL_ART, GraphicsStyle.HD_PIXEL_ART):
        # Pixel art is sprite-based; isometric pixel art is the more precise
        # 2.5D call rather than flat 2D.
        votes.add(
            Dimension.TWO_HALF_D if camera is Camera.ISOMETRIC else Dimension.TWO_D
        )

    if len(votes) == 1:
        return votes.pop()
    if votes:
        return Dimension.UNKNOWN  # signals disagree — never guess

    # No structured signal at all: explicit self-declared dimension in store copy.
    desc_votes = {
        dim for pattern, dim in _DIMENSION_DESC_PATTERNS if pattern.search(description)
    }
    if len(desc_votes) == 1:
        return desc_votes.pop()
    return Dimension.UNKNOWN


def classify(
    tags: list[tuple[str, int]],
    description: str = "",
    legal_notice: str = "",
) -> Classification:
    """tags: (name, votes) pairs from the store page tag list."""
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

    dimension = _best_tag_match(tags, _DIMENSION_TAGS)
    dimension_source: Literal["tag", "rule_based", "unknown"]
    if dimension is not None:
        dimension_source = "tag"
    else:
        dimension = _infer_dimension(camera, graphics, description)
        dimension_source = "rule_based" if dimension is not Dimension.UNKNOWN else "unknown"

    engine = GameEngine.UNKNOWN
    engine_corpus = f"{legal_notice}\n{description}"
    for pattern, candidate in _ENGINE_PATTERNS:
        if pattern.search(engine_corpus):
            engine = candidate
            break

    return Classification(
        dimension=dimension,
        camera=camera,
        graphics_style=graphics,
        engine=engine,
        dimension_source=dimension_source,
    )
