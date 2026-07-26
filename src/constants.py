from pathlib import Path


DEEZER_API = "https://api.deezer.com"
DEEZER_DELAY = 0.12 # ~50 requests / 5 seconds is the documented ceiling
SPOTIFY_DELAY = 0.10 #spotipy should handle rate limiting but just in case
CACHE_DIR = Path("cache")
SCOPES = "playlist-modify-private playlist-modify-public playlist-read-private user-library-read user-library-modify"

SPOTIFY_LIKED_SONGS_STRIDE = 20 #magic value, otherwise spotify returns "Too many uris requested". I think that the max is 40, but this already works
