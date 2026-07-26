from pathlib import Path

DEEZER_API = "https://api.deezer.com"
DEEZER_DELAY = 0.12 # ~50 requests / 5 seconds is the documented ceiling
SPOTIFY_DELAY = 0.10 #spotipy should handle rate limiting but just in case
SPOTIFY_PLAYLIST_STRIDE = 100 # documented max for playlist_add_items
CACHE_DIR = Path("cache")
CHECKPOINT_EVERY = 50 # tracks between cache writes during the long resolve loops
# user-read-private is what makes /me return `country`, which is used as the search
# market. Without it the field is absent entirely.
SCOPES = "playlist-modify-private playlist-modify-public playlist-read-private user-library-read user-library-modify user-read-private"

SPOTIFY_LIKED_SONGS_STRIDE = 20 #magic value, otherwise spotify returns "Too many uris requested". I think that the max is 40, but this already works
# "Liked Songs" has no batch endpoint that preserves order, so each track is its
# own request. Slow on purpose, see spotify_import_playlist.
SPOTIFY_LIKED_SONGS_DELAY = 1.0
