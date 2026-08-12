"""Community-hub follower count parsing.

The failure this pins: a game with no community hub returns HTTP 200 with a
"Steam Community :: Error" page. Validating on status code alone would record
those games as having zero followers, which is a different fact from "not
publicly available" and would quietly corrupt a shipped column.
"""

import pytest

from scraper.collectors.followers import parse_members_count


def test_real_members_page_yields_exact_count(members_html):
    assert parse_members_count(members_html) == 444348


def test_hubless_game_error_page_returns_none(members_error_html):
    """HTTP 200 + error page. None, never 0."""
    assert parse_members_count(members_error_html) is None


def test_none_is_not_zero(members_error_html):
    """Spelled out because `not 0` and `is None` behave alike in a truthiness
    check, and the difference is the entire point."""
    result = parse_members_count(members_error_html)
    assert result is None
    assert result != 0


@pytest.mark.parametrize(
    "html,expected",
    [
        ('<div class="pageLinks">1 - 50 of 444,315 Members</div>', 444315),
        ("of 42 Members", 42),
        ("OF 1,234 MEMBERS", 1234),
        ("of 1 234 567 Members", 1234567),
        ('{"member_count": 98765}', 98765),
    ],
)
def test_count_shapes(html, expected):
    assert parse_members_count(html) == expected


@pytest.mark.parametrize(
    "html",
    [
        "",
        "<title>Steam Community :: Error</title>",
        "of 5,000 Groups",          # right shape, wrong noun
        "no numbers here at all",
    ],
)
def test_unparsable_returns_none(html):
    assert parse_members_count(html) is None
