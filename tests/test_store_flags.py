"""Store-page flags Valve prints but appdetails omits.

Pinned against the real banner wording: these parsers fail silently — a markup
change yields False, not an exception, and the whole catalogue would quietly
read "not limited".
"""

from scraper.collectors.steam_sources import parse_store_flags

LIMITED_BANNER = """
<div class="learning_about"><span>Steam is learning about this game</span>
When Steam has learned more about this game, it may reappear.</div>
"""
AI_BANNER = """
<div id="game_area_content_descriptors"><h2>AI Generated Content Disclosure</h2>
<p>The developers describe how their game uses AI Generated Content like this:</p></div>
"""
CLEAN_PAGE = "<div class='game_area_description'>A perfectly ordinary store page.</div>"


def test_limited_banner_is_detected():
    assert parse_store_flags(LIMITED_BANNER).limited_profile is True


def test_ai_disclosure_is_detected():
    assert parse_store_flags(AI_BANNER).ai_disclosure is True


def test_a_clean_page_sets_neither():
    flags = parse_store_flags(CLEAN_PAGE)
    assert flags.limited_profile is False
    assert flags.ai_disclosure is False


def test_the_two_flags_are_independent():
    """A heavily-reviewed game can disclose AI; that is not a limited profile.

    Verified against this catalogue: one of the three most-reviewed games
    carries the AI disclosure and has full profile features.
    """
    flags = parse_store_flags(AI_BANNER)
    assert flags.ai_disclosure is True
    assert flags.limited_profile is False

    both = parse_store_flags(LIMITED_BANNER + AI_BANNER)
    assert both.limited_profile is True
    assert both.ai_disclosure is True


def test_the_alternate_limited_wording_is_accepted():
    assert parse_store_flags("<p>Profile Features Limited</p>").limited_profile is True
