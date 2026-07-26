import sys
import time
import unicodedata

import spotipy

import tqdm
from tqdm.contrib import tenumerate

from src.constants import CACHE_DIR, SCOPES, SPOTIFY_DELAY, SPOTIFY_LIKED_SONGS_STRIDE
from src.dtypes import Export, Track

def normalize_str(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return "".join(c for c in s if c.isalnum() or c.isspace()).strip()


def spotify_resolve_track(sp: spotipy.Spotify, track: Track, market: str) -> None:
    """Populate track.spotify_uri and track.match in place."""
    if track.isrc:
        res = sp.search(q=f"isrc:{track.isrc}", type="track", limit=1, market=market)
        items = res.get("tracks", {}).get("items", [])
        if items:
            track.spotify_uri, track.match = items[0]["uri"], "isrc"
            return

    query = f'track:"{track.title}" artist:"{track.artist}"'
    res = sp.search(q=query, type="track", limit=10, market=market)
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
                print(f"  ! {track}: {exc}", file=sys.stderr)
                export.save()
                raise
            if i % 50 == 0:
                export.save()
                print(f"  {i}/{len(pending)}")
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
    use_liked_songs = False
    print((
        f"Do you want the import target to be your \"Liked Songs\" playlist?"
        f"NOTE: This will take a while. Spotify does not provide any capability for sending sorted batches "
        f"of tracks to the \"Liked Songs\" playlist, so each add has to have a separate request in order "
        f"to preserve the original order. If you don't want original order preserved, you can modify the calls below "
        f"and remove the sleep & tqdm bar."
    ))
    print(f"Proceed to add {len(uris)} tracks to your \"Liked Songs\"? (y/N)")
    if input().strip().lower() == "y":
        use_liked_songs = True
    else:
        print(f"New playlist will be created using the exported playlist's name. You can change the name later in Spotify.")

    if use_liked_songs:
        for i in tqdm.tqdm(range(0, len(uris)), desc="Adding to Liked Songs", unit="track"):
            sp.current_user_saved_tracks_add([uris[i]])
            time.sleep(1)

        print(f"Added {len(uris)} tracks to your \"Liked Songs\"")
    else:
        print(f"Proceed to create Spotify playlist with {len(uris)} tracks? (y/N)")
        if input().strip().lower() != "y":
            print("Aborted.")
            return
    
        playlist = sp.current_user_playlist_create(
            name=export.title, public=False,
            description="Migrated from Deezer",
        )
        if not playlist or "id" not in playlist:
            raise RuntimeError("Failed to create Spotify playlist")
        print(f"Created: {playlist['external_urls']['spotify']}")

        STRIDE = 100
        for i in tqdm.tqdm(range(0, len(uris), STRIDE), desc="Adding to playlist", unit="batch"):
            sp.playlist_add_items(playlist["id"], uris[i:i + STRIDE])
        print(f"Added {len(uris)} tracks to Spotify playlist '{export.title}'")


def spotify_delete_liked_songs(sp: spotipy.Spotify) -> None:
    print(f"Are you sure you want to clear all tracks from your Spotify \"Liked Songs\" playlist? (y/N)")
    if input().strip().lower() != "y":
        print("Aborted.")
        return
    
    results = sp.current_user_saved_tracks(limit=SPOTIFY_LIKED_SONGS_STRIDE)
    total = results['total']
    print(f"Found {total} tracks in your \"Liked Songs\" playlist, removing them...")
    removed = 0
    for _ in tqdm.tqdm(range(0, total, SPOTIFY_LIKED_SONGS_STRIDE), desc="Removing from Liked Songs", unit="batch"):
        ids = [item['track']['id'] for item in results['items']]
        sp.current_user_saved_tracks_delete(ids)
        time.sleep(SPOTIFY_DELAY)
        removed += len(ids)
        print(f"Removed {removed}/{total} tracks...")
        results = sp.current_user_saved_tracks(limit=SPOTIFY_LIKED_SONGS_STRIDE)

    print(f"All {removed} tracks removed from your \"Liked Songs\" playlist.")


def spotify_client() -> tuple[spotipy.Spotify, str, str]:
    sp = spotipy.Spotify(
        auth_manager=spotipy.SpotifyOAuth(scope=SCOPES, cache_path=".cache-spotify"),
        retries=5, status_retries=5, backoff_factor=0.5,
    )
    print(f"Authenticated with Spotify, checking user info... (you're prompted to authorize in your browser if this is the first run)")
    me = sp.current_user()

    if not me or "id" not in me or "country" not in me:
        raise RuntimeError("Failed to get Spotify user info. Missing 'id' or 'country' in response.")
    
    return sp, me["id"], me.get("country")