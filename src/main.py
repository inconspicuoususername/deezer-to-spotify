"""
Migrate playlists from Deezer to Spotify, matching on ISRC where possible.

See README.md for setup.
"""

import argparse
import sys
import typing

from dotenv import load_dotenv
from spotipy.client import Spotify

from src.deezer import deezer_export_playlist
from src.dtypes import Export
from src.spotify import (
    spotify_client,
    spotify_delete_liked_songs,
    spotify_import_playlist,
)


def setup_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="phase", required=True)

    for name in ("export", "import", "run"):
        p = sub.add_parser(name)
        p.add_argument("playlist_ids", nargs="+")
        # Both flags always exist on the namespace, but each is only offered on
        # the phases it actually affects.
        p.set_defaults(refresh=False, dry_run=False)
        if name in ("export", "run"):
            p.add_argument("--refresh", action="store_true",
                           help="Ignore cache and re-fetch from Deezer")
        if name in ("import", "run"):
            p.add_argument("--dry-run", action="store_true",
                           help="Match and report, but don't create the playlist")

    sub.add_parser("test", help="Test Spotify authorization")
    sub.add_parser("clear_liked", help="Clear all tracks from your Spotify \"Liked Songs\" playlist")
    return parser.parse_args()


def run_test(sp: Spotify) -> int:
    try:
        results = sp.current_user_playlists()
        print("Authorized n stuff. playlists:")
        for item in (results or {}).get("items", []):
            print(f"- {item['name']}")
    except Exception as exc:
        print(f"Authorization failed: {exc}", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    load_dotenv()
    args = setup_args()

    spotify: tuple[Spotify, str] | None = None
    if args.phase in ("import", "run", "clear_liked", "test"):
        sp, user_id, market = spotify_client()
        print(f"Authenticated as {user_id} (market {market})")
        spotify = (sp, market)

    if args.phase == "test":
        sp, market = typing.cast(tuple[Spotify, str], spotify)
        return run_test(sp)

    if args.phase == "clear_liked":
        sp, market = typing.cast(tuple[Spotify, str], spotify)
        spotify_delete_liked_songs(sp)
        return 0

    failed = False
    for playlist_id in args.playlist_ids:
        print(f"\n=== {playlist_id} ===")
        try:
            if args.phase in ("export", "run"):
                export = deezer_export_playlist(playlist_id, refresh=args.refresh)
            else:
                export = Export.load(playlist_id)
                if export is None:
                    print("No cached export, run 'export' first.", file=sys.stderr)
                    failed = True
                    continue

            if args.phase in ("import", "run"):
                sp, market = typing.cast(tuple[Spotify, str], spotify)
                spotify_import_playlist(sp, market, export, dry_run=args.dry_run)

        except Exception as exc:
            print(f"Failed: {exc}", file=sys.stderr)
            failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
