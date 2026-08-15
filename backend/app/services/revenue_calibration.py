"""Check the estimator against games whose sales the developer disclosed.

Ten data points cannot fit a five-tier multiplier table — two games per tier
is noise, and a table fitted on noise looks authoritative while being
arbitrary. So this does the one thing ten points can honestly do: ask
whether the estimator is systematically off, and whether its bands are wide
enough to contain reality.

Two outputs, both deliberately blunt:

- `median_ratio` — actual copies over estimated copies, across the set. A
  value near 1 says the centring holds; 2 says every estimate is half what
  it should be.
- `in_band` — how many disclosures fell inside their own low-high band. A
  band that contains almost nothing is too narrow to be useful; one that
  contains everything may be too wide to be informative.

The decision rule refuses to act on small disagreements. With ten points the
sampling noise alone spans a wide interval, so a median ratio inside
NEUTRAL_LOW..NEUTRAL_HIGH is treated as "no evidence of bias" and the
constants are left exactly as they are. Outside it, a single global scalar
is proposed — never a per-tier one, and never without recording n alongside
it, because a factor measured on ten games is a sanity check wearing a
calibration's clothes.

Lower bounds are kept out of the ratio entirely, and this is the subtlest
rule here. About 85% of disclosures are round lower bounds ("over 250,000
copies"). When our estimate clears one, the true figure is unknown — it
could be anywhere above. When our estimate falls below one, we have proof of
an under-estimate. Feeding only the second group into a median would compute
a bias from the subsample selected for failing, and propose a correction far
larger than the population deserves. So:

- `median_ratio` uses EXACT disclosures only. Unbiased, and usually small.
- `bound_violations` counts estimates that fell below a stated floor. That
  is a proven failure rate, reported as its own number and never converted
  into a factor.
"""

import statistics
from dataclasses import dataclass, field

# Below/above these, a global correction is proposed. The width is set by
# what ten samples can distinguish, not by what would look precise.
NEUTRAL_LOW = 0.7
NEUTRAL_HIGH = 1.4

# Fewer than this and the report states a direction but proposes nothing.
MIN_SAMPLE_TO_ACT = 8


@dataclass(frozen=True)
class DisclosedSale:
    """One developer-stated figure, paired with what we estimated for it."""

    appid: int
    name: str
    actual_copies: int
    comparator: str          # '=' | '>='
    estimated_copies: int
    band_low: int
    band_high: int


@dataclass(frozen=True)
class CalibrationReport:
    sample: int
    median_ratio: float | None
    in_band: int
    exact_sample: int = 0
    bounds_checked: int = 0
    bound_violations: int = 0
    ratios: list[float] = field(default_factory=list)
    proposed_factor: float = 1.0
    verdict: str = ""
    bound_verdict: str = ""
    rows: list[tuple[str, float, bool]] = field(default_factory=list)


def _ratio(row: DisclosedSale) -> float | None:
    """actual / estimated for an EXACT disclosure only.

    Lower bounds are excluded in both directions. One the estimate clears
    proves nothing — the truth is somewhere above it. One the estimate misses
    proves an under-estimate, but collecting only those and taking their
    median measures the subsample selected for failing, not the population.
    Those are counted separately, as violations.
    """
    if row.estimated_copies <= 0 or row.comparator != "=":
        return None
    return row.actual_copies / row.estimated_copies


def calibrate(rows: list[DisclosedSale]) -> CalibrationReport:
    comparable = [(row, _ratio(row)) for row in rows]
    ratios = [r for _, r in comparable if r is not None]
    in_band = sum(1 for row in rows if row.band_low <= row.actual_copies <= row.band_high)

    bounds = [row for row in rows if row.comparator == ">=" and row.estimated_copies > 0]
    violations = [row for row in bounds if row.estimated_copies < row.actual_copies]
    bound_verdict = (
        f"{len(violations)} of {len(bounds)} lower-bound disclosures came in ABOVE "
        "our estimate — a proven under-estimate for those games. The rest only "
        "show the estimate clears a floor, which the true figure may exceed by "
        "any amount."
        if bounds
        else "no lower-bound disclosures to test against"
    )

    if not ratios:
        return CalibrationReport(
            sample=len(rows),
            median_ratio=None,
            in_band=in_band,
            bounds_checked=len(bounds),
            bound_violations=len(violations),
            bound_verdict=bound_verdict,
            verdict=(
                "no exact disclosures — the centring cannot be measured, only "
                "the floor test below"
            ),
        )

    median_ratio = round(statistics.median(ratios), 3)
    detail = [
        (row.name, round(ratio, 2), row.band_low <= row.actual_copies <= row.band_high)
        for row, ratio in comparable
        if ratio is not None
    ]

    if NEUTRAL_LOW <= median_ratio <= NEUTRAL_HIGH:
        verdict = (
            f"median ratio {median_ratio} sits inside the neutral band "
            f"({NEUTRAL_LOW}-{NEUTRAL_HIGH}) — no evidence of systematic bias, "
            "constants unchanged"
        )
        factor = 1.0
    elif len(ratios) < MIN_SAMPLE_TO_ACT:
        verdict = (
            f"median ratio {median_ratio} is outside the neutral band, but "
            f"{len(ratios)} comparable point(s) is too few to act on — "
            "reporting the direction only"
        )
        factor = 1.0
    else:
        factor = median_ratio
        direction = "under" if median_ratio > 1 else "over"
        verdict = (
            f"estimates read {direction} by a median factor of {median_ratio} "
            f"across {len(ratios)} disclosures — propose a single global scalar, "
            "recorded with its sample size"
        )

    return CalibrationReport(
        sample=len(rows),
        median_ratio=median_ratio,
        in_band=in_band,
        exact_sample=len(ratios),
        bounds_checked=len(bounds),
        bound_violations=len(violations),
        ratios=ratios,
        proposed_factor=factor,
        verdict=verdict,
        bound_verdict=bound_verdict,
        rows=detail,
    )
