import contextlib
import json

from src.dtypes import Export, Track


def track(deezer_id=1, **kw):
    base = dict(title="Song", artist="Artist", album="Album", duration=200)
    return Track(deezer_id=deezer_id, **{**base, **kw})


def write_raw(cache_dir, playlist_id, payload):
    (cache_dir / f"{playlist_id}.json").write_text(json.dumps(payload))


class TestRoundTrip:
    def test_survives_save_and_load(self, cache_dir):
        e = Export(playlist_id="42", title="Favorite tracks", total=2, tracks=[
            track(1, isrc="USRC12345678", isrc_checked=True, spotify_uri="spotify:track:a", match="isrc"),
            track(2),
        ])
        e.save()
        loaded = Export.load("42")
        assert loaded is not None
        assert (loaded.playlist_id, loaded.title, loaded.total) == ("42", "Favorite tracks", 2)
        assert [vars(t) for t in loaded.tracks] == [vars(t) for t in e.tracks]

    def test_missing_cache_returns_none(self, cache_dir):
        assert Export.load("nope") is None

    def test_unicode_is_not_escaped(self, cache_dir):
        Export(playlist_id="42", title="Björk", tracks=[]).save()
        assert "Björk" in (cache_dir / "42.json").read_text()


class TestAtomicSave:
    def test_leaves_no_temp_file_behind(self, cache_dir):
        Export(playlist_id="42", title="T", tracks=[track()]).save()
        assert list(cache_dir.glob("*.tmp")) == []

    def test_overwrites_cleanly_without_stale_content(self, cache_dir):
        Export(playlist_id="42", title="T", tracks=[track(i) for i in range(10)]).save()
        Export(playlist_id="42", title="T", tracks=[track(1)]).save()
        loaded = Export.load("42")
        assert loaded is not None and len(loaded.tracks) == 1

    def test_a_crashed_write_leaves_the_previous_cache_intact(self, cache_dir, monkeypatch):
        Export(playlist_id="42", title="Good", tracks=[track()]).save()

        e = Export(playlist_id="42", title="Bad", tracks=[track()])
        monkeypatch.setattr("src.dtypes.os.replace", lambda *a: (_ for _ in ()).throw(OSError("boom")))
        with contextlib.suppress(OSError):
            e.save()

        # The old file must still parse -- this is the whole point of write-then-rename.
        loaded = Export.load("42")
        assert loaded is not None and loaded.title == "Good"


class TestBackwardCompatibility:
    def test_cache_without_total_reads_as_complete(self, cache_dir):
        # Otherwise an old cache looks like a partially-fetched one and gets re-paged.
        write_raw(cache_dir, "42", {
            "playlist_id": "42", "title": "T",
            "tracks": [vars(track(i)) for i in range(3)],
        })
        loaded = Export.load("42")
        assert loaded is not None and loaded.total == 3

    def test_existing_isrc_implies_it_was_already_looked_up(self, cache_dir):
        # Regression: without isrc_checked, every ISRC-less track was re-fetched
        # from Deezer on every single run, forever.
        raw = vars(track(1, isrc="USRC12345678"))
        del raw["isrc_checked"]
        write_raw(cache_dir, "42", {"playlist_id": "42", "title": "T", "tracks": [raw]})
        loaded = Export.load("42")
        assert loaded is not None and loaded.tracks[0].isrc_checked is True

    def test_absent_isrc_is_rechecked_once(self, cache_dir):
        raw = vars(track(1))
        del raw["isrc_checked"]
        write_raw(cache_dir, "42", {"playlist_id": "42", "title": "T", "tracks": [raw]})
        loaded = Export.load("42")
        assert loaded is not None and loaded.tracks[0].isrc_checked is False

    def test_fields_dropped_since_the_cache_was_written_are_ignored(self, cache_dir):
        raw = vars(track(1))
        raw["some_removed_field"] = "x"
        write_raw(cache_dir, "42", {"playlist_id": "42", "title": "T", "tracks": [raw]})
        loaded = Export.load("42")
        assert loaded is not None and loaded.tracks[0].deezer_id == 1


class TestPartialFetchDetection:
    def test_short_track_list_is_recognisable_as_partial(self, cache_dir):
        Export(playlist_id="42", title="T", total=250,
               tracks=[track(i) for i in range(100)]).save()
        loaded = Export.load("42")
        assert loaded is not None
        assert len(loaded.tracks) < loaded.total  # what triggers a resume
