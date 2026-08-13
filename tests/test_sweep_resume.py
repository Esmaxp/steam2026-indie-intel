"""Where a re-run of a stopped disclosures sweep picks up.

The follower collector resumes for free — select_stale() skips whatever is
already fresh — so only the disclosure harvester needs this. It writes rows
only for the ~5% of games that announced a wishlist figure, which means
"already scanned" leaves no trace in the database for the other 95%, and a
re-run that started from appid 0 would spend hours re-reading news it has
already read.
"""

from app.services.sweeps import walk_position


def test_a_recent_run_reports_its_own_walk_position():
    assert walk_position({"appid": 2867471, "processed": 350}, "api") == (
        "appid",
        2867471,
    )


def test_an_older_run_falls_back_to_how_many_it_scanned():
    """Rows written before the walk position was recorded have only a count.
    The walk is appid-ordered, so the count still locates the position."""
    assert walk_position({"processed": 3700}, None) == ("scanned", 3700)


def test_a_cli_batch_count_is_refused_rather_than_guessed_at():
    """A CLI sweep runs as a series of 400-game containers and reports
    `processed` per batch. Read as a global position it would send the re-run
    back to the 350th game in the catalogue — hours of re-reading, presented
    as a resume."""
    assert walk_position({"processed": 350}, "cli") is None


def test_a_cli_run_still_resumes_when_it_reported_a_position():
    assert walk_position({"appid": 2986590, "processed": 350}, "cli") == (
        "appid",
        2986590,
    )


def test_a_run_that_got_nowhere_has_no_position():
    assert walk_position({}, "api") is None
    assert walk_position({"processed": 0}, "api") is None


def test_a_finished_run_resumes_from_where_it_stopped_not_what_it_selected():
    """The end-of-run summary reports `scanned` — games SELECTED, which the
    sweep script needs to detect the end of the catalogue. A run stopped early
    selected far more than it read, so reading `scanned` as a position would
    skip everything it never got to."""
    summary = {
        "scanned": 19228,   # selected
        "processed": 130,   # actually read
        "appid": 3312590,   # where it got to
        "stopped": True,
        "done": True,
    }
    assert walk_position(summary, "api") == ("appid", 3312590)
