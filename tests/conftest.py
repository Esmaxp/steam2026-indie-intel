"""Shared fixtures. Every test here is a PURE-function test: no database, no
network. That is deliberate — the parsers these cover fail SILENTLY (a markup
change yields zero rows, not an exception), so they must be pinned against
saved real payloads rather than live endpoints."""

import pathlib

import pytest

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def search_results_html() -> str:
    """Real store search rows, including a Sub_ package row."""
    return _read("search_results_page.html")


@pytest.fixture(scope="session")
def members_html() -> str:
    """Real community hub members page (contains 'of 444,348 Members')."""
    return _read("members_page.html")


@pytest.fixture(scope="session")
def members_error_html() -> str:
    """A hub-less game: HTTP 200 with a Steam Community error page."""
    return _read("members_error_page.html")
