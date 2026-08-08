"""Public, updatable constants for the team-cost budget heuristic.

MONTHLY_COST_PER_PERSON_USD approximates the *fully loaded* monthly cost of
one game developer (salary + taxes + overhead) by region.

Sources used for these 2025/2026 figures (update alongside the values):
- Kevuru Games, "Game Development Cost" (2025): region rate benchmarks
  https://kevurugames.com/blog/game-development-cost/
- levels.fyi / Glassdoor aggregate game-dev salary bands (2025), grossed up
  ~1.4x for employer costs and overhead.
These are coarse industry benchmarks, not measurements — which is exactly why
every budget number derived from them is labeled an estimate with its inputs.

REVENUE_TO_BUDGET_RATIO: public post-mortem analyses (notably GameDiscoverCo
newsletter pieces on indie break-even economics, 2023-2025) commonly treat a
healthy premium indie as grossing ~2.5x-5x its development budget over launch
year. Inverted: budget ≈ 20%-40% of gross revenue. A rule of thumb — always
surfaced as a range, never a fact.
"""

MONTHLY_COST_PER_PERSON_USD: dict[str, int] = {
    "north_america": 13000,
    "western_europe": 10000,
    "eastern_europe": 5500,
    "turkey": 4500,
    "latin_america": 4500,
    "east_asia": 8000,
    "southeast_asia": 3500,
    "oceania": 9500,
    "other": 6000,
}

COST_TABLE_SOURCE = (
    "Kevuru Games game-dev cost benchmarks (2025) + salary aggregates, "
    "grossed up ~1.4x for employer overhead"
)

# budget ≈ gross_revenue * [MIN_RATIO, MAX_RATIO]
REVENUE_TO_BUDGET_MIN_RATIO = 0.20
REVENUE_TO_BUDGET_MAX_RATIO = 0.40
RATIO_SOURCE = (
    "GameDiscoverCo public analyses of indie break-even economics (2023-2025): "
    "healthy premium indies gross ~2.5x-5x dev budget in launch year"
)
