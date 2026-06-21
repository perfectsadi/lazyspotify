"""Configuration loading for lazyspotify.

Credentials are looked up in this order:
  1. Environment variables: SPOTIPY_CLIENT_ID, SPOTIPY_CLIENT_SECRET,
     SPOTIPY_REDIRECT_URI
  2. Config file: ~/.config/lazyspotify/config.ini
  3. Interactive prompt on first run (saved to the config file for next time)
"""
from __future__ import annotations

import configparser
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "lazyspotify"
CONFIG_FILE = CONFIG_DIR / "config.ini"
CACHE_FILE = CONFIG_DIR / ".spotify-token-cache"

DEFAULT_REDIRECT_URI = "http://127.0.0.1:8080/callback"

SCOPES = " ".join(
    [
        "user-read-playback-state",
        "user-modify-playback-state",
        "user-read-currently-playing",
        "playlist-read-private",
        "playlist-read-collaborative",
        "user-library-read",
        "user-read-recently-played",
    ]
)


@dataclass
class Credentials:
    client_id: str
    client_secret: str
    redirect_uri: str


def _from_env() -> Optional[Credentials]:
    cid = os.environ.get("SPOTIPY_CLIENT_ID")
    secret = os.environ.get("SPOTIPY_CLIENT_SECRET")
    redirect = os.environ.get("SPOTIPY_REDIRECT_URI", DEFAULT_REDIRECT_URI)
    if cid and secret:
        return Credentials(cid, secret, redirect)
    return None


def _from_file() -> Optional[Credentials]:
    if not CONFIG_FILE.exists():
        return None
    parser = configparser.ConfigParser()
    parser.read(CONFIG_FILE)
    if "spotify" not in parser:
        return None
    section = parser["spotify"]
    try:
        return Credentials(
            client_id=section["client_id"],
            client_secret=section["client_secret"],
            redirect_uri=section.get("redirect_uri", DEFAULT_REDIRECT_URI),
        )
    except KeyError:
        return None


def _prompt_and_save() -> Credentials:
    print("lazyspotify needs a Spotify Developer app.")
    print("Create one at https://developer.spotify.com/dashboard and add")
    print(f"  {DEFAULT_REDIRECT_URI}")
    print("as a Redirect URI in the app settings (Edit Settings).\n")
    client_id = input("Client ID: ").strip()
    client_secret = input("Client Secret: ").strip()
    redirect_uri = input(f"Redirect URI [{DEFAULT_REDIRECT_URI}]: ").strip() or DEFAULT_REDIRECT_URI

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    parser = configparser.ConfigParser()
    parser["spotify"] = {
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
    }
    with open(CONFIG_FILE, "w") as fh:
        parser.write(fh)
    os.chmod(CONFIG_FILE, 0o600)
    print(f"Saved to {CONFIG_FILE}\n")
    return Credentials(client_id, client_secret, redirect_uri)


def load_credentials() -> Credentials:
    return _from_env() or _from_file() or _prompt_and_save()
