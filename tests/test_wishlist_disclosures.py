"""Developer-disclosure extraction from Steam news.

Every sentence below is real, taken from the dry-run audits. These rows are
written at CONFIRMED — the highest trust tier in this codebase and the only
one the wishlist column displays — so a false positive here is a fabricated
fact on a shipped page.
"""

import datetime

import pytest

from scraper.collectors.wishlist_disclosures import (
    find_wishlist_disclosures,
    parse_amount,
)

EPOCH = int(datetime.datetime(2026, 7, 6, tzinfo=datetime.timezone.utc).timestamp())


def extract(text: str, title: str = "Update"):
    """-> [(value, comparator)] for one news post."""
    items = [{"title": title, "contents": text, "date": EPOCH, "url": "https://s.tld/p"}]
    return [(d.wishlists, d.comparator) for d in find_wishlist_disclosures(1, items)]


# --------------------------------------------------------------- amounts --

@pytest.mark.parametrize(
    "raw,suffix,expected",
    [
        ("50,000", None, 50000),
        ("500 000", None, 500000),     # space-grouped; parsed as 000 before
        ("125.000", None, 125000),     # dot-grouped (de locale)
        ("125.4", "K", 125400),
        ("1.2", "M", 1200000),
        ("8500", None, 8500),
        ("2026", None, None),          # bare year
        ("2019", None, None),
    ],
)
def test_parse_amount(raw, suffix, expected):
    assert parse_amount(raw, suffix) == expected


# ------------------------------------------------------- must be REJECTED --

@pytest.mark.parametrize(
    "label,text",
    [
        ("promotional target", "Help us go all the way to 1,000,000 wishlists"),
        ("goal", "Our goal is 200,000 wishlists"),
        ("conditional", "will be back once Nadir achieves it's 50k wishlist milestone"),
        ("historical", "seeing that number climb from 1,700 wishlists to this high"),
        ("historical w/ tilde", "We started at ~10 000 Wishlists and will close with 130 000"),
        ("delta verb", "We've gained 2500 Wishlists in just the last two weeks"),
        ("delta plus-sign", "Thank you so much for the +2,000 wishlists"),
        ("chart rank", "about to crack the top 1000 wishlisted unreleased games"),
        ("upper bound", "Akatori has almost reached 200 000 wishlists on Steam"),
        ("upper bound 2", "we are now approaching 25,000 wishlists"),
        ("upper bound 3", "I received just shy of a 1000 wishlists"),
        ("number in game name", "Make sure you've wishlisted 1348 Ex Voto on Steam"),
        ("bare year", "Launching in 2026 with wishlists climbing"),
        ("absurd value", "Patch 539073139032455 Wishlist fixes"),
        ("no figure", "Nothing numeric here at all"),
    ],
)
def test_rejected(label, text):
    assert extract(text) == [], label


# ------------------------------------------------------- must be ACCEPTED --

@pytest.mark.parametrize(
    "text,expected",
    [
        ("We just passed 50,000 wishlists!", [(50000, ">=")]),
        ("Thank you for 700,000 wishlists", [(700000, ">=")]),
        ("Gecko Gods has officially reached 140,000 wishlists", [(140000, ">=")]),
        ("Romestead Hits 250k Wishlists", [(250000, ">=")]),
        ("Since January we've gone from 6k to 90k Wishlists", [(90000, ">=")]),
        ("Legends of Astravia has accumulated over 250 wishlists", [(250, ">=")]),
        ("To celebrate reaching over 2,000 wishlists", [(2000, ">=")]),
        ("Wishlists: 40 000", [(40000, ">=")]),
        # No bound word BEFORE the figure and not a round multiple, so this
        # stays exact: "125.4K reached" states a figure, it does not claim
        # "at least 125,400" the way "reached 140,000" does.
        ("[b]125.4K wishlists[/b] reached", [(125400, "=")]),
    ],
)
def test_accepted(text, expected):
    assert extract(text) == expected


def test_exact_figure_keeps_equals():
    """Not a round multiple and no bound claimed -> '=' is what was said."""
    assert extract("Exactly 43,217 wishlists today") == [(43217, "=")]


def test_unrelated_over_does_not_create_a_bound():
    """'over the course of' is not a lower-bound claim about the figure."""
    assert extract(
        "we are sitting at 125.4K wishlists on Steam over the course of a single week"
    ) == [(125400, "=")]


# ------------------------------------------------------------- behaviour --

def test_restatement_dropped_and_earliest_date_wins():
    items = [
        {"title": "a", "contents": "We hit 400,000 wishlists!", "url": "u1",
         "date": int(datetime.datetime(2026, 7, 9, tzinfo=datetime.timezone.utc).timestamp())},
        {"title": "b", "contents": "Still going at 400,000 wishlists.", "url": "u2",
         "date": int(datetime.datetime(2026, 8, 6, tzinfo=datetime.timezone.utc).timestamp())},
    ]
    found = find_wishlist_disclosures(1, items)
    assert [d.wishlists for d in found] == [400000]
    assert found[0].disclosed_on == datetime.date(2026, 7, 9)


def test_disclosed_on_comes_from_the_post_date():
    found = find_wishlist_disclosures(
        1, [{"title": "t", "contents": "50,000 wishlists", "url": "u", "date": EPOCH}]
    )
    assert found[0].disclosed_on == datetime.date(2026, 7, 6)


def test_undated_post_is_skipped():
    assert find_wishlist_disclosures(
        1, [{"title": "t", "contents": "10,000 wishlists", "date": 0, "url": "u"}]
    ) == []


def test_excerpt_always_contains_the_figure():
    """The dry-run CSV is the human gate; an excerpt missing its own number
    makes that gate unusable."""
    long_text = "word " * 60 + "we passed 50,000 wishlists today " + "more " * 60
    found = find_wishlist_disclosures(
        1, [{"title": "t", "contents": long_text, "date": EPOCH, "url": "u"}]
    )
    assert "50,000" in found[0].excerpt
