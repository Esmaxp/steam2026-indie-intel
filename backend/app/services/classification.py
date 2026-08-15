"""The two axes combined into one label — and the confidence to read it with.

    effort ─┬─ high ─┬─ traction high → HIGH_EFFORT_HIGH_TRACTION
            │        └─ traction low  → HIGH_EFFORT_LOW_TRACTION   ← the point
            └─ low  ─┬─ traction high → LOW_EFFORT_HIGH_TRACTION
                     └─ traction low  → LOW_EFFORT_LOW_TRACTION

HIGH_EFFORT_LOW_TRACTION is why this exists. A serious game nobody found is not
noise; it is the most interesting row in the catalogue for anyone looking for
something to publish, port or cover. Every other methodology collapses it into
the bottom of the market because it only counts sales.

INSUFFICIENT_DATA is a real answer, not a failure: a game released three weeks
ago, or one whose store page has not been read yet, has not earned a verdict.
Nothing is ever deleted — the label sits beside the raw signals, and both
scoring modules can be re-run when the weights change.
"""

from dataclasses import dataclass

from app.services import effort_score, traction_score

HIGH_EFFORT_HIGH_TRACTION = "HIGH_EFFORT_HIGH_TRACTION"
HIGH_EFFORT_LOW_TRACTION = "HIGH_EFFORT_LOW_TRACTION"
LOW_EFFORT_HIGH_TRACTION = "LOW_EFFORT_HIGH_TRACTION"
LOW_EFFORT_LOW_TRACTION = "LOW_EFFORT_LOW_TRACTION"
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

# `mixed` effort sits with the serious side: the class exists for games that
# did several things right, and calling them low-effort would reproduce exactly
# the mistake this design is here to avoid.
_HIGH_EFFORT_CLASSES = (effort_score.CLASS_SERIOUS, effort_score.CLASS_MIXED)

CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"

# Below this many observed effort signals the score is a guess about a page we
# barely read, whatever number it produced.
_EFFORT_SIGNALS_FOR_CONFIDENCE = 4


@dataclass(frozen=True)
class Classification:
    label: str
    confidence: str


def classify(
    effort: effort_score.EffortResult, traction: traction_score.TractionResult
) -> Classification:
    if effort.effort_class == effort_score.CLASS_UNKNOWN:
        return Classification(INSUFFICIENT_DATA, CONFIDENCE_LOW)
    if traction.status != traction_score.STATUS_MEASURED:
        # Effort is known, traction is not yet knowable. Say so rather than
        # guessing a quadrant from half the evidence.
        return Classification(INSUFFICIENT_DATA, CONFIDENCE_LOW)

    high_effort = effort.effort_class in _HIGH_EFFORT_CLASSES
    high_traction = traction.traction_class == traction_score.CLASS_STRONG

    if high_effort:
        label = HIGH_EFFORT_HIGH_TRACTION if high_traction else HIGH_EFFORT_LOW_TRACTION
    else:
        label = LOW_EFFORT_HIGH_TRACTION if high_traction else LOW_EFFORT_LOW_TRACTION

    return Classification(label, _confidence(effort, traction))


def _confidence(
    effort: effort_score.EffortResult, traction: traction_score.TractionResult
) -> str:
    """How much evidence stands behind the label, not how strong the label is.

    Two things weaken it: few effort signals actually observed, and a traction
    reading resting on a single metric. A game scored on reviews alone can move
    class the day a follower sweep lands.
    """
    thin_effort = effort.observed < _EFFORT_SIGNALS_FOR_CONFIDENCE
    thin_traction = traction.observed <= 1
    if thin_effort and thin_traction:
        return CONFIDENCE_LOW
    if thin_effort or thin_traction:
        return CONFIDENCE_MEDIUM
    return CONFIDENCE_HIGH
