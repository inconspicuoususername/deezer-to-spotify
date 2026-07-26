import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Literal

from src.constants import CACHE_DIR


@dataclass
class Track:
    deezer_id: int
    title: str
    artist: str
    album: str
    duration: int  # seconds
    isrc: str | None = None
    # Distinguishes "not looked up yet" from "looked up, Deezer has no ISRC".
    # Without it, tracks Deezer has no ISRC for get re-fetched on every run.
    isrc_checked: bool = False
    spotify_uri: str | None = None
    match: Literal["isrc", "fuzzy", "none", "pending"] = "pending"

    def __str__(self) -> str:
        return f"{self.artist} - {self.title}"

    @classmethod
    def from_cache(cls, raw: dict) -> "Track":
        """Build from a cached dict, tolerating fields added or dropped since it was written."""
        known = {f.name for f in fields(cls)}
        data = {k: v for k, v in raw.items() if k in known}
        # Caches written before isrc_checked existed: a present ISRC means the
        # lookup already happened. An absent one is indistinguishable from a
        # track Deezer has no ISRC for, so it gets looked up once more.
        data.setdefault("isrc_checked", bool(data.get("isrc")))
        return cls(**data)


@dataclass
class Export:
    playlist_id: str
    title: str
    # nb_tracks as reported by Deezer, so an interrupted fetch can tell a
    # partial track list from a complete one.
    total: int = 0
    tracks: list[Track] = field(default_factory=list)

    def path(self) -> Path:
        return CACHE_DIR / f"{self.playlist_id}.json"

    def save(self) -> None:
        CACHE_DIR.mkdir(exist_ok=True)
        payload = {
            "playlist_id": self.playlist_id,
            "title": self.title,
            "total": self.total,
            "tracks": [asdict(t) for t in self.tracks],
        }
        # Write-then-rename: these are checkpoints, and a Ctrl-C partway through
        # a plain write would leave truncated JSON that no longer loads.
        path = self.path()
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
        os.replace(tmp, path)

    @classmethod
    def load(cls, playlist_id: str) -> "Export | None":
        path = CACHE_DIR / f"{playlist_id}.json"
        if not path.exists():
            return None
        raw = json.loads(path.read_text())
        tracks = [Track.from_cache(t) for t in raw["tracks"]]
        return cls(
            playlist_id=raw["playlist_id"],
            title=raw["title"],
            # Caches written before `total` existed are assumed complete.
            total=raw.get("total", len(tracks)),
            tracks=tracks,
        )
