import sys
import time

import requests
from tqdm import tqdm
from tqdm.contrib import tenumerate

from deezer_to_spotify.constants import CHECKPOINT_EVERY, DEEZER_API, DEEZER_DELAY
from deezer_to_spotify.dtypes import Export, Track


def deezer_get(path: str) -> dict:
    resp = requests.get(f"{DEEZER_API}{path}", timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict) and "error" in data:
        err = data["error"]
        # By far the most common cause: the playlist isn't public, and without
        # OAuth these endpoints can't see it.
        hint = ""
        if isinstance(err, dict) and err.get("type") == "DataException":
            hint = " (is the playlist public? this tool can only read public playlists)"
        raise RuntimeError(f"Deezer error on {path}: {err}{hint}")
    return data


def deezer_fetch_tracks(export: Export) -> None:
    """Page through the playlist, appending tracks to `export` and checkpointing as it goes."""
    index = len(export.tracks)
    if index:
        print(f"Resuming fetch of '{export.title}' at {index}/{export.total}")
    else:
        print(f"Fetching '{export.title}' from Deezer")

    while True:
        page = deezer_get(f"/playlist/{export.playlist_id}/tracks?index={index}&limit=100")
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
        export.save()  # checkpoint, so an interrupt here doesn't discard the pages already fetched
        print(f"  {index}/{export.total or '?'}")
        if "next" not in page:
            break
        time.sleep(DEEZER_DELAY)

    export.total = len(export.tracks)
    export.save()
    print(f"Fetched '{export.title}': {len(export.tracks)} tracks")


def deezer_export_playlist(playlist_id: str, refresh: bool = False) -> Export:
    """Fetch the playlist and enrich every track with its ISRC.

    Resumes from cache in both directions: a partial track list picks up at the
    page it stopped on, and tracks whose ISRC was already looked up are skipped.
    """
    export = None if refresh else Export.load(playlist_id)

    if export is None:
        meta = deezer_get(f"/playlist/{playlist_id}")
        export = Export(
            playlist_id=playlist_id,
            title=meta.get("title", f"Deezer {playlist_id}"),
            total=meta.get("nb_tracks", 0),
        )
        deezer_fetch_tracks(export)
    elif len(export.tracks) < export.total:
        deezer_fetch_tracks(export)

    pending = [t for t in export.tracks if not t.isrc_checked]
    if not pending:
        print(f"'{export.title}': export complete ({len(export.tracks)} tracks)")
        return export

    print(f"Resolving ISRCs for {len(pending)} tracks "
          f"(~{int(len(pending) * DEEZER_DELAY)}s)")
    for i, track in tenumerate(pending, 1, desc="Resolving ISRCs", unit="track"):
        try:
            detail = deezer_get(f"/track/{track.deezer_id}")
        except (requests.RequestException, RuntimeError) as exc:
            # Left unchecked so the next run retries it.
            tqdm.write(f"  ! {track}: {exc}", file=sys.stderr)
        else:
            track.isrc = detail.get("isrc") or None
            track.isrc_checked = True
        if i % CHECKPOINT_EVERY == 0:
            export.save()
        time.sleep(DEEZER_DELAY)

    export.save()
    have = sum(1 for t in export.tracks if t.isrc)
    print(f"ISRC coverage: {have}/{len(export.tracks)}")
    return export
