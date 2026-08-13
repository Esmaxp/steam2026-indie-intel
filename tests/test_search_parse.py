"""Store search row parsing.

The bug this pins: rows were keyed on data-ds-appid, whose value for a
PACKAGE row is a comma-separated appid list. Taking the first element admitted
a bundled game under the package's title and release date, and let the same
appid arrive twice from two different package rows.
"""

from bs4 import BeautifulSoup

from scraper.discovery.search import parse_results_html, parse_search_row


def _anchors(html: str):
    return BeautifulSoup(html, "html.parser").select("a.search_result_row")


def test_package_rows_are_dropped(search_results_html):
    anchors = _anchors(search_results_html)
    subs = [a for a in anchors if str(a.get("data-ds-itemkey", "")).startswith("Sub_")]
    assert subs, "fixture must contain a Sub_ row or it is not testing anything"
    for anchor in subs:
        assert parse_search_row(anchor) is None


def test_first_appid_of_a_package_is_not_admitted(search_results_html):
    """Sub_1686522 carries '2054970,2593180,2593190,2593290'. Under the old
    parser 2054970 was admitted as if the row were that game."""
    appids = {row.appid for row in parse_results_html(search_results_html)}
    packaged_first = 2054970
    subs = [
        a for a in _anchors(search_results_html)
        if str(a.get("data-ds-itemkey", "")).startswith("Sub_")
        and str(packaged_first) in str(a.get("data-ds-appid", ""))
    ]
    if subs:
        assert packaged_first not in appids


def test_app_rows_parse_with_name(search_results_html):
    rows = parse_results_html(search_results_html)
    assert rows, "fixture should yield at least one App_ row"
    for row in rows:
        assert isinstance(row.appid, int) and row.appid > 0
        assert row.name


def test_no_duplicate_appids(search_results_html):
    appids = [row.appid for row in parse_results_html(search_results_html)]
    assert len(appids) == len(set(appids))


def test_itemkey_wins_over_appid_attribute():
    html = (
        '<a class="search_result_row" data-ds-itemkey="App_777" '
        'data-ds-appid="111,222"><span class="title">Game</span></a>'
    )
    row = parse_search_row(_anchors(html)[0])
    assert row is not None and row.appid == 777


def test_fallback_rejects_multi_appid_when_itemkey_absent():
    """Degrade to skipping a row, never to mis-attributing it."""
    html = '<a class="search_result_row" data-ds-appid="1,2,3"><span class="title">P</span></a>'
    assert parse_search_row(_anchors(html)[0]) is None


def test_fallback_accepts_single_appid_when_itemkey_absent():
    html = '<a class="search_result_row" data-ds-appid="42"><span class="title">Solo</span></a>'
    row = parse_search_row(_anchors(html)[0])
    assert row is not None and row.appid == 42


def test_row_without_title_is_skipped():
    html = '<a class="search_result_row" data-ds-itemkey="App_5"></a>'
    assert parse_search_row(_anchors(html)[0]) is None
