from dataclasses import dataclass, asdict, field
import json
from pathlib import Path
from typing import Literal

from src.constants import CACHE_DIR

@dataclass
class Track:
    deezer_id: int
    title: str
    artist: str
    album: str
    duration: int #seconds
    isrc: str | None = None
    spotify_uri: str | None = None
    match: Literal["isrc", "fuzzy", "none", "pending"] = "pending"

    def __str__(self) -> str:
        return f"{self.artist} - {self.title}"


@dataclass
class Export:
    playlist_id: str
    title: str
    tracks: list[Track] = field(default_factory=list)

    def path(self) -> Path:
        return CACHE_DIR / f"{self.playlist_id}.json"

    def save(self) -> None:
        CACHE_DIR.mkdir(exist_ok=True)
        payload = {
            "playlist_id": self.playlist_id,
            "title": self.title,
            "tracks": [asdict(t) for t in self.tracks],
        }
        self.path().write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    @classmethod
    def load(cls, playlist_id: str) -> "Export | None":
        path = CACHE_DIR / f"{playlist_id}.json"
        if not path.exists():
            return None
        raw = json.loads(path.read_text())
        return cls(
            playlist_id=raw["playlist_id"],
            title=raw["title"],
            tracks=[Track(**t) for t in raw["tracks"]],
        )
