from pydantic import BaseModel


class MonthPoint(BaseModel):
    month: int  # 1–12 (2026)
    released: int
    upcoming: int


class BreakdownPoint(BaseModel):
    key: str
    count: int


class ChartsOut(BaseModel):
    """Aggregations for the analytics section. Counts only — never invented
    values; 'unknown' buckets are shown as such, not hidden."""

    releases_by_month: list[MonthPoint]
    by_dimension: list[BreakdownPoint]
    by_engine: list[BreakdownPoint]
    by_graphics_style: list[BreakdownPoint]
    top_genres: list[BreakdownPoint]


class SuccessBandPoint(BaseModel):
    key: str
    label: str
    count: int
    share: float           # count / games_scored
    baseline_share: float  # what an average genre would show — true by construction
    min_percentile: float


class GenreBands(BaseModel):
    """One genre's standing, compact enough to show ten side by side."""

    genre: str
    games_scored: int
    bands: list[SuccessBandPoint]


class ClassificationRow(BaseModel):
    """One quadrant of the effort × traction split.

    `highlight` marks HIGH_EFFORT_LOW_TRACTION so the UI can surface it
    whatever the sort order: it is the group this catalogue exists to find,
    and it will never be the biggest row.
    """

    label: str
    count: int  # kept as the original field name: total_count's twin, for existing callers
    share: float  # count / catalogue total — unchanged meaning
    released_count: int = 0
    upcoming_count: int = 0
    total_count: int = 0  # released_count + upcoming_count, i.e. count
    released_share: float = 0.0  # count / all released games
    upcoming_share: float = 0.0  # count / all upcoming games
    highlight: bool = False
    by_confidence: dict[str, int] = {}


class ClassificationSummaryOut(BaseModel):
    total: int
    released_total: int = 0
    upcoming_total: int = 0
    rows: list[ClassificationRow]


class GenreSuccessSlice(BaseModel):
    """One genre's share of the catalogue's top-decile games.

    Counted by each game's PRIMARY genre so the slices partition the successful
    set exactly once — games carry several genres, and counting a game under
    all of them would make the parts sum past the whole.
    """

    genre: str
    count: int          # top-decile games whose primary genre this is
    share: float        # count / all top-decile games — the pie slice
    scored: int         # ranked games in this genre (any position)
    rate: float         # count / scored — the genre's own success rate
    over_index: float   # rate vs the catalogue average rate


class GenreSuccessOverviewOut(BaseModel):
    """Every top genre at once — the cross-genre comparison.

    A single genre's distribution is nearly the catalogue's by construction
    (the bands are catalogue-wide percentiles), so the interesting quantity is
    the deviation between genres. That only reads if the genres are shown
    together.
    """

    measure: str
    cohort: str
    method: str
    notes: str
    genres: list[GenreBands]
    # Who the top-decile games actually are, by primary genre.
    composition: list[GenreSuccessSlice]
    top_band_label: str


class GenreRevenueSlice(BaseModel):
    """One genre's share of the games clearing a revenue threshold.

    Counted per GENRE TAG, not per game: a game carrying three genres is
    counted under all three. The percentages therefore divide the tag total,
    not the game total — which is why they still sum to 100% while
    `count` values add up past `game_count`.
    """

    genre: str
    count: int
    pct: float


class RevenueMethodOut(BaseModel):
    """The arithmetic behind the numbers, shipped with them.

    The UI renders its explanation from these fields rather than repeating
    the constants in the frontend: a second copy of a number is a second
    number to keep correct.
    """

    formula: str
    constants: dict[str, float]
    calibration_factor: float
    calibration_sample: int
    min_reviews: int


class GenreRevenueDistributionOut(BaseModel):
    """Genre mix of the games estimated to clear a net-revenue threshold.

    `estimable_total` is the honest denominator: most of the catalogue has
    too few reviews to estimate at all, and a share of "all games" would
    read as though those were measured failures.
    """

    tier: str
    min_revenue: float
    game_count: int
    total_revenue_mid: float
    estimable_total: int
    catalogue_total: int
    share_of_estimable: float
    share_of_catalogue: float
    sources_used: dict[str, int]
    median_spread: float | None
    method: RevenueMethodOut
    genres: list[GenreRevenueSlice]


class GenreRevenueBand(BaseModel):
    """One mutually exclusive revenue band within a genre.

    Exclusive so the bands can be pie slices: they partition the genre's
    estimable games and their shares sum to 1. `cumulative_pct` carries what
    the exclusive split throws away — the share earning AT LEAST this band's
    floor — because that is the number two genres can be compared on, and it
    costs nothing to derive.
    """

    label: str
    min_revenue: float
    max_revenue: float | None   # None on the open-ended top band
    game_count: int
    pct: float                  # game_count / the genre's estimable games
    cumulative_count: int       # games in this band or any band above it
    cumulative_pct: float
    total_revenue_mid: float


class GenreTierBreakdownOut(BaseModel):
    """A single genre split across revenue bands.

    The denominator is the genre's games that CAN be estimated, not all its
    games: dividing by a population most of which has too few reviews to
    judge would report a pass rate that is really a coverage rate.
    """

    genre: str
    total_games: int         # games in this genre with a revenue estimate
    genre_total: int         # games in this genre, estimable or not
    catalogue_total: int
    method: RevenueMethodOut
    bands: list[GenreRevenueBand]


class GenreSuccessOut(BaseModel):
    """Where one genre's games sit among their release-month peers.

    A ranking of a measured value (Steam's own review count), not an estimate:
    no sales figure is derived, so there is no multiplier to disagree with.
    Games that cannot be ranked are counted in the two exclusion fields rather
    than placed in a band.
    """

    genre: str
    games_in_genre: int
    games_scored: int
    games_excluded_unreleased: int
    games_excluded_no_reviews: int
    measure: str
    cohort: str
    method: str
    notes: str
    bands: list[SuccessBandPoint]
