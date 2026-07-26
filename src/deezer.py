import sys

import requests
from tqdm.contrib import tenumerate

from src.constants import DEEZER_API, DEEZER_DELAY
from src.dtypes import Export, Track
import time


def deezer_get(path: str) -> dict:
    resp = requests.get(f"{DEEZER_API}{path}", timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict) and "error" in data:
        raise RuntimeError(f"Deezer error on {path}: {data['error']}")
    return data


def deezer_export_playlist(playlist_id: str, refresh: bool = False) -> Export:
    """Fetch the playlist and enrich every track with its ISRC.

    Resumes from cache: tracks that already have an ISRC are skipped, so an
    interrupted run picks up roughly where it stopped.
    """
    export = None if refresh else Export.load(playlist_id)

    if export is None:
        meta = deezer_get(f"/playlist/{playlist_id}")
        export = Export(
            playlist_id=playlist_id,
            title=meta.get("title", f"Deezer {playlist_id}"),
        )
        index = 0
        print(f"Fetching '{export.title}' from Deezer")
        while True:
            page = deezer_get(f"/playlist/{playlist_id}/tracks?index={index}&limit=100")
            batch = page.get("data", [])
            if not batch:
                break
            for t in batch:
                export.tracks.append(Track(
                    deezer_id=t["id"],
                    title=t["title"],
                    artist=t.get("artist", {}).get("name", ""),
                    album=t.get("album", {}).get("title", ""),
                    duration=t.get("duration", 0),
                ))
            index += len(batch)
            if "next" not in page:
                break
            print(f"  {index}/{page.get('total', '?')}")
            time.sleep(DEEZER_DELAY)
        export.save()
        print(f"Fetched '{export.title}': {len(export.tracks)} tracks")

    pending = [t for t in export.tracks if t.isrc is None and t.match == "pending"]
    if not pending:
        print(f"'{export.title}': export complete ({len(export.tracks)} tracks)")
        return export

    print(f"Resolving ISRCs for {len(pending)} tracks "
          f"(~{int(len(pending) * DEEZER_DELAY)}s)")
    for i, track in tenumerate(pending, 1, desc="Resolving ISRCs", unit="track"):
        try:
            detail = deezer_get(f"/track/{track.deezer_id}")
            track.isrc = detail.get("isrc") or None
        except Exception as exc:
            print(f"  ! {track}: {exc}", file=sys.stderr)
        if i % 50 == 0:
            export.save()          # checkpoint
            print(f"  {i}/{len(pending)}")
        time.sleep(DEEZER_DELAY)

    export.save()
    have = sum(1 for t in export.tracks if t.isrc)
    print(f"ISRC coverage: {have}/{len(export.tracks)}")
    return export
