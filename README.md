# deezer-to-spotify

Migrates Deezer playlists to Spotify, matching tracks by ISRC. ISRC identifies a specific recording, so you get the same master instead of a remaster, live cut, or sped-up edit that happens to share a name.

Falls back to a scoped title/artist search when Deezer has no ISRC for a track.

## Why not Soundiiz / TuneMyMusic

They work fine, and if you have a handful of short playlists they're faster than this. Free tiers cap playlist size (Soundiiz at 200 tracks). But I had way more in my playlist than that, and didn't feel like paying them money.

## Setup

### Deezer

Deezer doesn't have new API app registration anymore, so OAuth isn't available. The public read endpoints work without a token, which means the playlist(s) you're importing must be set to public during the import. You can set it back afterwards.

Playlist ID is the last path segment of the URL:

    https://www.deezer.com/us/playlist/1234567890  ->  1234567890

### Spotify

As of February 2026 the Web API requires the developer account to have Premium. A free account is rejected at token exchange with `blocked from accessing the Web API`.

1. Create an app at https://developer.spotify.com/dashboard
2. Redirect URI, exactly: `http://127.0.0.1:8888/callback`
   (`localhost` is deprecated and will be rejected)
3. Select **Web API** when asked which APIs you'll use

Development mode is fine, since the five-user cap is irrelevant for personal use, and no endpoint here needs extended quota.

## Usage

Ensure that you have all the relevant values in the `.env.example` in your own `.env`

```sh
# Phase 1: Deezer -> cache/<id>.json (one request per track for ISRC)
python3 -m src.main export 1234567890

# Phase 2: match and create. --dry-run reports without writing.
python3 -m src.main import 1234567890 --dry-run
python3 -m src.main import 1234567890

# Or both at once
python3 -m src.main run 1234567890 9876543210

# If you wanna wipe your liked songs:
python3 -m src.main clear_liked
```

State lives in `cache/`. Both phases checkpoint every 50 tracks and skip already-resolved entries, so an interrupted run resumes instead of starting over. `--refresh` forces a re-fetch from Deezer.

## Output

`cache/<id>-report.md` outputs fuzzy matches and songs with no Spotify equivalent. This is usually because of regional licensing gaps.

As for the playlists themselves, order is preserved. This poses a slight issue with Liked Songs, since Spotify's API used to have a route that allowed you to impose a custom order or inserted Liked Songs, but that has since been deprecated. So you'll have to wait a second per song when importing into Liked Songs.

## Note

This was done with the assistence of Claude. If you want to do this without the use of AI, be my guest. I didn't have the time to write everything manually. 