"""Thin wrapper around spotipy exposing exactly what lazyspotify needs."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import spotipy
from spotipy.oauth2 import SpotifyOAuth

from . import config


class SpotifyError(Exception):
    """Raised when a Spotify API call fails, with a human-readable message."""


class Client:
    def __init__(self) -> None:
        config.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        creds = config.load_credentials()
        auth_manager = SpotifyOAuth(
            client_id=creds.client_id,
            client_secret=creds.client_secret,
            redirect_uri=creds.redirect_uri,
            scope=config.SCOPES,
            cache_path=str(config.CACHE_FILE),
            open_browser=True,
        )
        self.sp = spotipy.Spotify(auth_manager=auth_manager)
        self._device_id: Optional[str] = None

    # ---- internal helpers -------------------------------------------------
    def _call(self, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except spotipy.SpotifyException as exc:
            raise SpotifyError(exc.msg or str(exc)) from exc
        except spotipy.oauth2.SpotifyOauthError as exc:
            raise SpotifyError(f"Auth error: {exc}") from exc

    def _active_device(self) -> Optional[str]:
        if self._device_id:
            return self._device_id
        devices = self.get_devices()
        for d in devices:
            if d.get("is_active"):
                return d["id"]
        return devices[0]["id"] if devices else None

    # ---- playback state -----------------------------------------------------
    def current_playback(self) -> Optional[Dict[str, Any]]:
        return self._call(self.sp.current_playback)

    def queue(self) -> Dict[str, Any]:
        return self._call(self.sp.queue) or {}

    # ---- transport controls ---------------------------------------------------
    def play_pause(self, is_playing: bool) -> None:
        device = self._active_device()
        if is_playing:
            self._call(self.sp.pause_playback, device_id=device)
        else:
            self._call(self.sp.start_playback, device_id=device)

    def next_track(self) -> None:
        self._call(self.sp.next_track, device_id=self._active_device())

    def previous_track(self) -> None:
        self._call(self.sp.previous_track, device_id=self._active_device())

    def seek(self, position_ms: int) -> None:
        self._call(self.sp.seek_track, position_ms, device_id=self._active_device())

    def set_volume(self, percent: int) -> None:
        percent = max(0, min(100, percent))
        self._call(self.sp.volume, percent, device_id=self._active_device())

    def toggle_shuffle(self, state: bool) -> None:
        self._call(self.sp.shuffle, state, device_id=self._active_device())

    def set_repeat(self, state: str) -> None:
        """state: 'track' | 'context' | 'off'"""
        self._call(self.sp.repeat, state, device_id=self._active_device())

    # ---- playing things ---------------------------------------------------------
    def play_uris(self, uris: List[str]) -> None:
        self._call(self.sp.start_playback, device_id=self._active_device(), uris=uris)

    def play_context(self, context_uri: str, offset_uri: Optional[str] = None) -> None:
        offset = {"uri": offset_uri} if offset_uri else None
        self._call(
            self.sp.start_playback,
            device_id=self._active_device(),
            context_uri=context_uri,
            offset=offset,
        )

    def add_to_queue(self, uri: str) -> None:
        self._call(self.sp.add_to_queue, uri, device_id=self._active_device())

    # ---- browsing -----------------------------------------------------------------
    def search(self, query: str, types: str = "track,artist,album,playlist", limit: int = 10):
        return self._call(self.sp.search, q=query, type=types, limit=limit) or {}

    def my_playlists(self, limit: int = 50) -> List[Dict[str, Any]]:
        results = self._call(self.sp.current_user_playlists, limit=limit)
        return results.get("items", []) if results else []

    def playlist_tracks(self, playlist_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        results = self._call(self.sp.playlist_items, playlist_id, limit=limit)
        items = results.get("items", []) if results else []
        return [it["track"] for it in items if it.get("track")]

    # ---- devices ----------------------------------------------------------------------
    def get_devices(self) -> List[Dict[str, Any]]:
        results = self._call(self.sp.devices)
        return results.get("devices", []) if results else []

    def transfer_playback(self, device_id: str, play: bool = True) -> None:
        self._call(self.sp.transfer_playback, device_id, force_play=play)
        self._device_id = device_id
