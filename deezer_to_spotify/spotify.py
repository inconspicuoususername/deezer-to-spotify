import sys
import time
import unicodedata

import spotipy
from tqdm import tqdm
from tqdm.contrib import tenumerate

from deezer_to_spotify.constants import (
    CACHE_DIR,
    CHECKPOINT_EVERY,
    SCOPES,
    SPOTIFY_DELAY,
    SPOTIFY_LIKED_SONGS_DELAY,
    SPOTIFY_LIKED_SONGS_STRIDE,
    SPOTIFY_PLAYLIST_STRIDE,
)
from deezer_to_spotify.dtypes import Export, Track


def require[T](value: T | None, what: str) -> T:
    """spotipy types every response as optional; treat a missing one as fatal."""
    if value is None:
        raise RuntimeError(f"Spotify returned no data for {what}")
    return value


def normalize_str(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = "".join(c for c in s if c.isalnum() or c.isspace())
    # Dropping punctuation leaves runs of spaces behind ("Rock & Roll" -> "rock  roll"),
    # which breaks the substring comparisons below.
    return " ".join(s.split())


def search_field(value: str) -> str:
    """Field queries are quote-delimited, so a quote in the value truncates the query."""
    return value.replace('"', " ").strip()


def spotify_resolve_track(sp: spotipy.Spotify, track: Track, market: str) -> None:
    """Populate track.spotify_uri and track.match in place."""
    if track.isrc:
        res = require(sp.search(q=f"isrc:{track.isrc}", type="track", limit=1, market=market), "isrc search")
        items = res.get("tracks", {}).get("items", [])
        if items:
            track.spotify_uri, track.match = items[0]["uri"], "isrc"
            return

    query = f'track:"{search_field(track.title)}" artist:"{search_field(track.artist)}"'
    res = require(sp.search(q=query, type="track", limit=10, market=market), "track search")
    items = res.get("tracks", {}).get("items", [])

    want_title, want_artist = normalize_str(track.title), normalize_str(track.artist)
    for item in items:
        got_title = normalize_str(item["name"])
        artists = [normalize_str(a["name"]) for a in item["artists"]]
        drift = abs(item["duration_ms"] / 1000 - track.duration)
        title_ok = want_title in got_title or got_title in want_title
        artist_ok = any(want_artist in a or a in want_artist for a in artists)
        if title_ok and artist_ok and (track.duration == 0 or drift <= 8):
            track.spotify_uri, track.match = item["uri"], "fuzzy"
            return

    track.spotify_uri, track.match = None, "none"


def spotify_import_playlist(
        sp: spotipy.Spotify,
        market: str,
        export: Export,
        dry_run: bool = False) -> None:
    pending = [t for t in export.tracks if t.match == "pending"]
    if pending:
        print(f"Searching Spotify for {len(pending)} tracks")
        for i, track in tenumerate(pending, 1, desc="Resolving tracks", unit="track"):
            try:
                spotify_resolve_track(sp, track, market)
            except Exception as exc:
                tqdm.write(f"  ! {track}: {exc}", file=sys.stderr)
                export.save()
                raise
            if i % CHECKPOINT_EVERY == 0:
                export.save()
            time.sleep(SPOTIFY_DELAY)
        export.save()

    # Preserve playlist order, drop misses, dedupe (Spotify won't).
    uris, seen = [], set()
    for t in export.tracks:
        if t.spotify_uri and t.spotify_uri not in seen:
            seen.add(t.spotify_uri)
            uris.append(t.spotify_uri)

    by_isrc = sum(1 for t in export.tracks if t.match == "isrc")
    fuzzy = [t for t in export.tracks if t.match == "fuzzy"]
    misses = [t for t in export.tracks if t.match == "none"]

    print(f"\nMatched {len(uris)}/{len(export.tracks)} unique "
          f"({by_isrc} exact, {len(fuzzy)} fuzzy, {len(misses)} missing)")

    report = CACHE_DIR / f"{export.playlist_id}-report.md"
    lines = [f"# {export.title}", "",
             f"- Exact (ISRC): {by_isrc}",
             f"- Fuzzy: {len(fuzzy)}",
             f"- Not found: {len(misses)}", ""]
    if fuzzy:
        lines += ["## Fuzzy matches, verify these", ""]
        lines += [f"- {t}  _({t.album})_" for t in fuzzy] + [""]
    if misses:
        lines += ["## Couldn't find on Spotify", ""]
        lines += [f"- {t}  _({t.album})_" for t in misses] + [""]
    report.write_text("\n".join(lines))
    print(f"Report: {report}")

    if dry_run:
        print("Dry run, nothing created.")
        return
    if not uris:
        print("Nothing to add.")
        return

    #deezer doesn't have a distinction between a regular playlist and a favorite playlist, but spotify does.
    print(
        'Do you want the import target to be your "Liked Songs" playlist?\n'
        "NOTE: This will take a while. Spotify does not provide any capability for sending sorted\n"
        'batches of tracks to the "Liked Songs" playlist, so each add has to have a separate request\n'
        "in order to preserve the original order."
    )
    print(f"Proceed to add {len(uris)} tracks to your \"Liked Songs\"? (y/N)")

    if input().strip().lower() == "y":
        # Deezer's API returns favorites oldest-first (the web player displays them
        # newest-first), and "Liked Songs" sorts by date added with the newest on top.
        # NOTE: a curated playlist comes back from the API in its display order,
        # with no reversal to cancel, so importing one into "Liked Songs" lands
        # inverted. Use these with a real playlist instead
        for uri in tqdm(uris, desc="Adding to Liked Songs", unit="track"):
            sp.current_user_saved_tracks_add([uri])
            time.sleep(SPOTIFY_LIKED_SONGS_DELAY)
        print(f"Added {len(uris)} tracks to your \"Liked Songs\"")
        return

    print("New playlist will be created using the exported playlist's name. You can change the name later in Spotify.")
    print(f"Proceed to create Spotify playlist with {len(uris)} tracks? (y/N)")
    if input().strip().lower() != "y":
        print("Aborted.")
        return

    playlist = require(sp.current_user_playlist_create(
        name=export.title, public=False,
        description="Migrated from Deezer",
    ), "playlist creation")
    if "id" not in playlist:
        raise RuntimeError("Failed to create Spotify playlist")
    print(f"Created: {playlist['external_urls']['spotify']}")

    for i in tqdm(range(0, len(uris), SPOTIFY_PLAYLIST_STRIDE), desc="Adding to playlist", unit="batch"):
        sp.playlist_add_items(playlist["id"], uris[i:i + SPOTIFY_PLAYLIST_STRIDE])
    print(f"Added {len(uris)} tracks to Spotify playlist '{export.title}'")


def spotify_delete_liked_songs(sp: spotipy.Spotify) -> None:
    print("Are you sure you want to clear all tracks from your Spotify \"Liked Songs\" playlist? (y/N)")
    if input().strip().lower() != "y":
        print("Aborted.")
        return

    results = require(sp.current_user_saved_tracks(limit=SPOTIFY_LIKED_SONGS_STRIDE), "saved tracks")
    total = results["total"]
    if not total:
        print("No tracks in your \"Liked Songs\" playlist.")
        return

    print(f"Found {total} tracks in your \"Liked Songs\" playlist, removing them...")
    # Deleting shifts everything down, so this always re-reads from offset 0.
    # Bounded in case a delete silently doesn't stick, rather than spinning forever.
    max_batches = total // SPOTIFY_LIKED_SONGS_STRIDE + 10
    removed = 0
    with tqdm(total=total, desc="Removing from Liked Songs", unit="track") as bar:
        for _ in range(max_batches):
            ids = [item["track"]["id"] for item in results["items"] if item.get("track")]
            if not ids:
                break
            sp.current_user_saved_tracks_delete(ids)
            removed += len(ids)
            bar.update(len(ids))
            time.sleep(SPOTIFY_DELAY)
            results = require(sp.current_user_saved_tracks(limit=SPOTIFY_LIKED_SONGS_STRIDE), "saved tracks")
        else:
            print("Gave up after too many batches, some tracks may remain.", file=sys.stderr)

    print(f"{removed} tracks removed from your \"Liked Songs\" playlist.")


def spotify_client() -> tuple[spotipy.Spotify, str, str]:
    sp = spotipy.Spotify(
        auth_manager=spotipy.SpotifyOAuth(scope=SCOPES, cache_path=".cache-spotify"),
        retries=5, status_retries=5, backoff_factor=0.5,
    )
    print("Authenticated with Spotify, checking user info... (you're prompted to authorize in your browser if this is the first run)")
    me = require(sp.current_user(), "the current user")

    if "id" not in me or "country" not in me:
        raise RuntimeError("Failed to get Spotify user info. Missing 'id' or 'country' in response.")

    return sp, me["id"], me["country"]
