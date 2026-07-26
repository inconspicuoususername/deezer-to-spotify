#!/usr/bin/env python3
"""
Migrate playlists from Deezer to Spotify, matching on ISRC where possible.

See README.md for setup.
"""

import argparse
import sys
import typing
from dotenv import load_dotenv
from spotipy.client import Spotify

load_dotenv()

from src.dtypes import Export
from src.deezer import deezer_export_playlist
from src.spotify import spotify_client, spotify_delete_liked_songs, spotify_import_playlist

def setup_args():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="phase", required=True)

    def add_playlist_args(p):
        p.add_argument("playlist_ids", nargs="+")
        p.add_argument("--refresh", action="store_true",
                    help="Ignore cache and re-fetch from Deezer")
        p.add_argument("--dry-run", action="store_true",
                    help="Match and report, but don't create the playlist")

    for name in ("export", "import", "run"):
        add_playlist_args(sub.add_parser(name))

    sub.add_parser("test", help="Test Spotify authorization")
    sub.add_parser("clear_liked", help="Clear all tracks from your Spotify \"Liked Songs\" playlist")
    args = parser.parse_args()
    return args

def main() -> int:
    args = setup_args()

    use_spotify = args.phase not in ("export")

    sp = user_id = market = None
    if use_spotify:
        sp, user_id, market = spotify_client()
        print(f"Authenticated as {user_id} (market {market})")
        if sp is None or user_id is None or market is None:
            raise RuntimeError("Spotify client could not be initialized")

    sp = typing.cast(Spotify, sp)
    user_id = typing.cast(str, user_id)
    market = typing.cast(str, market)

    if args.phase in ("test"):
        try:
            results = sp.current_user_playlists()
            print("Authorized n stuff. playlists:")
            for item in results['items']:
                print(f"- {item['name']}")
        except Exception as e:
            print(f"Authorization failed: {e}")

        return 0

    if args.phase in ("clear_liked"):
        spotify_delete_liked_songs(sp)
        return 0

    for playlist_id in args.playlist_ids:
        print(f"\n=== {playlist_id} ===")
        try:
            if args.phase in ("export", "run"):
                export = deezer_export_playlist(playlist_id, refresh=args.refresh)
            else:
                export = Export.load(playlist_id)
                if export is None:
                    print("No cached export, run 'export' first.", file=sys.stderr)
                    continue

            if args.phase in ("import", "run"):
                spotify_import_playlist(
                    sp, 
                    market, 
                    export, 
                    dry_run=args.dry_run
                )
            else:
                print(f"Nothing to do for {playlist_id}.")

        except Exception as exc:
            print(f"Failed: {exc}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())