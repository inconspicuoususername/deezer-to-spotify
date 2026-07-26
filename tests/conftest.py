import pytest

import src.dtypes


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    """Point Export's cache at a tmp dir so tests never touch the real cache/."""
    monkeypatch.setattr(src.dtypes, "CACHE_DIR", tmp_path)
    return tmp_path


class FakeSpotify:
    """Minimal stand-in for spotipy.Spotify, covering only what resolve uses."""

    def __init__(self, isrc_items=(), search_items=(), search_returns_none=False):
        self.isrc_items = list(isrc_items)
        self.search_items = list(search_items)
        self.search_returns_none = search_returns_none
        self.queries = []

    def search(self, q, type="track", limit=10, market=None):
        self.queries.append(q)
        if self.search_returns_none:
            return None
        items = self.isrc_items if q.startswith("isrc:") else self.search_items
        return {"tracks": {"items": items}}


def spotify_item(name, artists, duration_s, uri="spotify:track:abc"):
    return {
        "name": name,
        "uri": uri,
        "duration_ms": int(duration_s * 1000),
        "artists": [{"name": a} for a in artists],
    }
