"""is_released and coming_soon must never both be true.

They are two views of one fact, read by different parts of the app: the
dashboard's "Coming soon" tile counts `coming_soon`, the table's Upcoming
filter tests `is_released`. When a row set both, the two disagreed by exactly
the number of such rows — which is how this was found.
"""

import datetime

import pytest

from scraper.discovery.release_date import ParsedRelease
from scraper.discovery.service import release_flags

TODAY = datetime.date(2026, 8, 14)


def dated(year=2026, month=8, day=10) -> ParsedRelease:
    return ParsedRelease(date=datetime.date(year, month, day), raw="Aug 10, 2026", year=year)


UNDATED = ParsedRelease(date=None, raw="Coming soon", year=2026)


@pytest.mark.parametrize(
    ("label", "release", "coming_soon"),
    [
        ("past date, Steam says upcoming", dated(), True),
        ("past date, Steam says released", dated(), False),
        ("future date, Steam says upcoming", dated(month=12), True),
        ("no date, Steam says upcoming", UNDATED, True),
        ("no date, no flag", UNDATED, None),
        ("past date, no flag", dated(), None),
        ("future date, no flag", dated(month=12), None),
    ],
)
def test_the_two_flags_are_never_both_true(label, release, coming_soon):
    is_released, still_upcoming = release_flags(release, coming_soon, TODAY)
    assert not (is_released and still_upcoming), label
    assert is_released or still_upcoming, f"{label}: a game must be one or the other"


def test_steams_own_flag_wins_over_a_date_that_has_passed():
    """A listed date that slipped is not a release. Valve clears the flag at
    the real launch, so the flag is the better evidence."""
    is_released, coming_soon = release_flags(dated(), coming_soon=True, today=TODAY)
    assert (is_released, coming_soon) == (False, True)


def test_a_dated_release_without_the_flag_counts_as_released():
    is_released, coming_soon = release_flags(dated(), coming_soon=False, today=TODAY)
    assert (is_released, coming_soon) == (True, False)


def test_no_date_cannot_be_released_even_if_the_flag_is_clear():
    is_released, coming_soon = release_flags(UNDATED, coming_soon=False, today=TODAY)
    assert is_released is False


def test_without_the_flag_the_date_decides():
    assert release_flags(dated(), None, TODAY)[0] is True
    assert release_flags(dated(month=12), None, TODAY)[0] is False
