import pytest

from src.dtypes import Track
from src.spotify import normalize_str, search_field, spotify_resolve_track
from tests.conftest import FakeSpotify, spotify_item


def track(title="Song", artist="Artist", duration=200, isrc=None):
    return Track(deezer_id=1, title=title, artist=artist, album="Album",
                 duration=duration, isrc=isrc)


class TestNormalizeStr:
    def test_lowercases_and_strips_combining_accents(self):
        assert normalize_str("Björk") == "bjork"
        assert normalize_str("Sigur Rós") == "sigur ros"

    def test_struck_through_letters_survive_normalisation(self):
        # Known limitation, not a bug: NFKD only splits base+combining pairs, and
        # 'ł' (U+0142) is an atomic codepoint. So a track spelled "Przybyłowicz"
        # on one service and "Przybylowicz" on the other won't match on that word.
        assert normalize_str("Marcin Przybyłowicz") == "marcin przybyłowicz"

    def test_collapses_gaps_left_by_dropped_punctuation(self):
        # Regression: punctuation used to be dropped in place, leaving double
        # spaces that broke the substring comparisons in the fuzzy matcher.
        assert normalize_str("Rock & Roll") == "rock roll"
        assert normalize_str("Bohemian Rhapsody - 2011 Mix") == "bohemian rhapsody 2011 mix"
        assert "  " not in normalize_str("a  -  b   &   c")

    def test_keeps_apostrophe_words_joined(self):
        assert normalize_str("Don't Stop") == "dont stop"


class TestSearchField:
    def test_strips_quotes_that_would_truncate_the_query(self):
        # Regression: an unescaped quote closed the field early and corrupted
        # the whole query.
        assert '"' not in search_field('He said "Hi"')

    def test_leaves_ordinary_text_alone(self):
        assert search_field("Blinding Lights") == "Blinding Lights"


class TestResolveTrack:
    def test_isrc_hit_wins_and_skips_the_text_search(self):
        sp = FakeSpotify(isrc_items=[spotify_item("Whatever", ["Nobody"], 999)])
        t = track(isrc="USRC12345678")
        spotify_resolve_track(sp, t, "US")
        assert (t.match, t.spotify_uri) == ("isrc", "spotify:track:abc")
        assert sp.queries == ["isrc:USRC12345678"]

    def test_falls_back_to_text_search_when_isrc_misses(self):
        sp = FakeSpotify(isrc_items=[], search_items=[spotify_item("Song", ["Artist"], 200)])
        t = track(isrc="USRC12345678")
        spotify_resolve_track(sp, t, "US")
        assert t.match == "fuzzy"
        assert len(sp.queries) == 2

    def test_duration_drift_beyond_eight_seconds_is_rejected(self):
        sp = FakeSpotify(search_items=[spotify_item("Song", ["Artist"], 215)])
        t = track(duration=200)
        spotify_resolve_track(sp, t, "US")
        assert (t.match, t.spotify_uri) == ("none", None)

    def test_drift_within_tolerance_is_accepted(self):
        sp = FakeSpotify(search_items=[spotify_item("Song", ["Artist"], 205)])
        t = track(duration=200)
        spotify_resolve_track(sp, t, "US")
        assert t.match == "fuzzy"

    def test_unknown_duration_skips_the_drift_check(self):
        sp = FakeSpotify(search_items=[spotify_item("Song", ["Artist"], 999)])
        t = track(duration=0)
        spotify_resolve_track(sp, t, "US")
        assert t.match == "fuzzy"

    def test_wrong_artist_is_rejected(self):
        sp = FakeSpotify(search_items=[spotify_item("Song", ["Someone Else"], 200)])
        t = track(duration=200)
        spotify_resolve_track(sp, t, "US")
        assert t.match == "none"

    def test_first_acceptable_candidate_wins(self):
        sp = FakeSpotify(search_items=[
            spotify_item("Song", ["Wrong"], 200, uri="spotify:track:no"),
            spotify_item("Song", ["Artist"], 200, uri="spotify:track:yes"),
        ])
        t = track(duration=200)
        spotify_resolve_track(sp, t, "US")
        assert t.spotify_uri == "spotify:track:yes"

    def test_quotes_in_metadata_do_not_leak_into_the_query(self):
        sp = FakeSpotify(search_items=[])
        spotify_resolve_track(sp, track(title='The "Best" Song'), "US")
        field_query = sp.queries[-1]
        # Exactly the four delimiters the query template supplies, no strays.
        assert field_query.count('"') == 4

    def test_empty_response_is_fatal_rather_than_silently_unmatched(self):
        sp = FakeSpotify(search_returns_none=True)
        with pytest.raises(RuntimeError, match="no data"):
            spotify_resolve_track(sp, track(), "US")
