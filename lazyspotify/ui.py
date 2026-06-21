"""curses TUI for lazyspotify."""
from __future__ import annotations

import curses
import locale
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from .client import Client, SpotifyError

locale.setlocale(locale.LC_ALL, "")

TABS = ["Playlists", "Search", "Queue", "Devices"]

POLL_INTERVAL = 3.0
DEVICE_POLL_INTERVAL = 15.0

REPEAT_CYCLE = ["off", "context", "track"]
REPEAT_LABEL = {"off": "Repeat: Off", "context": "Repeat: All", "track": "Repeat: One"}


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def fmt_time(ms: Optional[int]) -> str:
    if ms is None or ms < 0:
        return "0:00"
    total_seconds = int(ms / 1000)
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes}:{seconds:02d}"


def truncate(s: str, width: int) -> str:
    if width <= 0:
        return ""
    if len(s) <= width:
        return s
    if width <= 1:
        return s[:width]
    return s[: width - 1] + "…"


def safe_addstr(win, y, x, text, attr=0):
    try:
        maxy, maxx = win.getmaxyx()
        if 0 <= y < maxy and 0 <= x < maxx:
            win.addstr(y, x, text[: max(0, maxx - x)], attr)
    except curses.error:
        pass


class Row:
    __slots__ = ("kind", "label", "sub", "data", "selectable")

    def __init__(self, kind: str, label: str, sub: str = "", data: Any = None, selectable: bool = True):
        self.kind = kind
        self.label = label
        self.sub = sub
        self.data = data
        self.selectable = selectable


class State:
    """Shared between the poller thread and the UI thread."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.playback: Optional[Dict[str, Any]] = None
        self.playback_time: float = 0.0
        self.devices: List[Dict[str, Any]] = []
        self.status: str = "Welcome to lazyspotify. Press ? for help."
        self.error: str = ""


# ---------------------------------------------------------------------------
# app
# ---------------------------------------------------------------------------
class App:
    def __init__(self, stdscr, client: Client):
        self.stdscr = stdscr
        self.client = client
        self.state = State()
        self.stop_event = threading.Event()

        self.tab_index = 0
        self.selected: Dict[int, int] = {i: 0 for i in range(len(TABS))}
        self.scroll: Dict[int, int] = {i: 0 for i in range(len(TABS))}

        self.playlists: List[Dict[str, Any]] = []
        self.current_playlist: Optional[Dict[str, Any]] = None
        self.current_playlist_tracks: List[Dict[str, Any]] = []

        self.search_query = ""
        self.search_rows: List[Row] = []
        self.queue_rows: List[Row] = []
        self.device_rows: List[Row] = []

        self.show_help = False

        curses.curs_set(0)
        self.stdscr.keypad(True)
        self.stdscr.timeout(250)
        self._init_colors()
        self._load_playlists()
        self._refresh_devices()

        self.poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self.poll_thread.start()

    # ---- setup ------------------------------------------------------------
    def _init_colors(self) -> None:
        self.has_color = curses.has_colors()
        if not self.has_color:
            return
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_GREEN, -1)
        curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_GREEN)
        curses.init_pair(3, curses.COLOR_YELLOW, -1)
        curses.init_pair(4, curses.COLOR_RED, -1)
        curses.init_pair(5, curses.COLOR_CYAN, -1)

    def _color(self, n: int) -> int:
        return curses.color_pair(n) if self.has_color else 0

    def _load_playlists(self) -> None:
        try:
            self.playlists = self.client.my_playlists()
            self.state.status = f"Loaded {len(self.playlists)} playlists."
        except SpotifyError as exc:
            self.state.error = str(exc)

    def _refresh_devices(self) -> None:
        try:
            devices = self.client.get_devices()
            with self.state.lock:
                self.state.devices = devices
        except SpotifyError as exc:
            self.state.error = str(exc)

    # ---- background polling ------------------------------------------------
    def _poll_loop(self) -> None:
        last_device_poll = 0.0
        while not self.stop_event.is_set():
            try:
                playback = self.client.current_playback()
                with self.state.lock:
                    self.state.playback = playback
                    self.state.playback_time = time.monotonic()
                    self.state.error = ""
            except SpotifyError as exc:
                with self.state.lock:
                    self.state.error = str(exc)
            now = time.monotonic()
            if now - last_device_poll > DEVICE_POLL_INTERVAL:
                try:
                    devices = self.client.get_devices()
                    with self.state.lock:
                        self.state.devices = devices
                    last_device_poll = now
                except SpotifyError:
                    pass
            self.stop_event.wait(POLL_INTERVAL)

    # ---- main loop --------------------------------------------------------
    def main_loop(self) -> None:
        try:
            while True:
                self._layout()
                self._draw()
                ch = self.stdscr.getch()
                if ch == -1 or ch == curses.KEY_RESIZE:
                    continue
                if not self._handle_key(ch):
                    break
        finally:
            self.stop_event.set()

    def _layout(self) -> None:
        self.height, self.width = self.stdscr.getmaxyx()
        self.sidebar_w = max(16, min(22, self.width // 4))
        self.content_x = self.sidebar_w + 2
        self.content_w = max(10, self.width - self.content_x - 1)
        self.now_playing_h = 4
        self.status_h = 1
        self.list_top = 1
        self.list_bottom = max(self.list_top, self.height - self.now_playing_h - self.status_h - 1)
        self.list_h = max(1, self.list_bottom - self.list_top)

    # ---- drawing ------------------------------------------------------------
    def _draw(self) -> None:
        stdscr = self.stdscr
        stdscr.erase()
        self._draw_sidebar()
        self._draw_main()
        self._draw_now_playing()
        self._draw_status()
        if self.show_help:
            self._draw_help()
        stdscr.refresh()

    def _draw_sidebar(self) -> None:
        safe_addstr(self.stdscr, 0, 0, " lazyspotify ".ljust(self.sidebar_w), curses.A_BOLD | self._color(3))
        for i, name in enumerate(TABS):
            y = self.list_top + i
            label = f" {i + 1}. {name}"
            attr = self._color(2) | curses.A_BOLD if i == self.tab_index else curses.A_NORMAL
            safe_addstr(self.stdscr, y, 0, label.ljust(self.sidebar_w), attr)
        divider_h = self.height - self.status_h
        for y in range(divider_h):
            safe_addstr(self.stdscr, y, self.sidebar_w, "│")

    def _draw_main(self) -> None:
        rows = self._current_rows()
        sel = self.selected[self.tab_index]
        if sel < self.scroll[self.tab_index]:
            self.scroll[self.tab_index] = sel
        if sel >= self.scroll[self.tab_index] + self.list_h:
            self.scroll[self.tab_index] = sel - self.list_h + 1
        start = max(0, self.scroll[self.tab_index])
        visible = rows[start:start + self.list_h]
        for i, row in enumerate(visible):
            y = self.list_top + i
            idx = start + i
            attr = curses.A_NORMAL
            if row.kind == "header":
                attr = self._color(3) | curses.A_BOLD
            elif idx == sel:
                attr = self._color(2)
            text = f"{row.label}  {row.sub}" if row.sub else row.label
            safe_addstr(self.stdscr, y, self.content_x, truncate(text, self.content_w), attr)
        if not rows:
            safe_addstr(self.stdscr, self.list_top, self.content_x, "(nothing here yet)", self._color(5))

    def _draw_now_playing(self) -> None:
        with self.state.lock:
            playback = self.state.playback
            fetched_at = self.state.playback_time
        y0 = self.height - self.now_playing_h - self.status_h
        safe_addstr(self.stdscr, y0, 0, "─" * self.width)
        if not playback or not playback.get("item"):
            safe_addstr(self.stdscr, y0 + 1, 1, "Nothing is playing right now.", self._color(5))
            return

        item = playback["item"]
        name = item.get("name", "Unknown")
        artists = ", ".join(a["name"] for a in item.get("artists", []))
        is_playing = playback.get("is_playing", False)
        progress_ms = playback.get("progress_ms", 0) or 0
        if is_playing:
            progress_ms += max(0, (time.monotonic() - fetched_at) * 1000)
        duration_ms = item.get("duration_ms", 1) or 1
        progress_ms = min(progress_ms, duration_ms)

        icon = "▶" if is_playing else "⏸"
        title_line = f"{icon}  {name} — {artists}"
        safe_addstr(self.stdscr, y0 + 1, 1, truncate(title_line, self.width - 2), self._color(1) | curses.A_BOLD)

        bar_width = max(10, self.width - 16)
        filled = int(bar_width * (progress_ms / duration_ms))
        bar = "█" * filled + "─" * (bar_width - filled)
        time_str = f"{fmt_time(progress_ms)}/{fmt_time(duration_ms)}"
        safe_addstr(self.stdscr, y0 + 2, 1, bar, self._color(1))
        safe_addstr(self.stdscr, y0 + 2, 1 + bar_width + 1, time_str)

        shuffle = "on" if playback.get("shuffle_state") else "off"
        repeat = REPEAT_LABEL.get(playback.get("repeat_state", "off"), "Repeat: Off")
        device = playback.get("device") or {}
        volume = device.get("volume_percent")
        vol_str = f"{volume}%" if volume is not None else "?"
        meta = f"Shuffle: {shuffle}   {repeat}   Vol: {vol_str}   Device: {device.get('name', '—')}"
        safe_addstr(self.stdscr, y0 + 3, 1, truncate(meta, self.width - 2), self._color(5))

    def _draw_status(self) -> None:
        y = self.height - 1
        with self.state.lock:
            err = self.state.error
            status = self.state.status
        if err:
            safe_addstr(self.stdscr, y, 0, truncate(f" ! {err}", self.width), self._color(4) | curses.A_BOLD)
        else:
            hint = "?:help  1-4:tabs  j/k:move  enter:select  space:play/pause  /:search  q:quit"
            safe_addstr(self.stdscr, y, 0, truncate(f" {status or hint}", self.width), self._color(5))

    def _draw_help(self) -> None:
        lines = [
            "lazyspotify — keybindings",
            "",
            "1-4 / Tab        switch panel",
            "j/k, ↑/↓         move selection",
            "g / G            jump to top / bottom",
            "Enter            play / open selection",
            "Backspace/Esc    go back",
            "Space or p       play / pause",
            "n / b            next / previous track",
            "+ / -            volume up / down",
            "s                toggle shuffle",
            "r                cycle repeat mode",
            "a                add selection to queue",
            "/                search",
            "R                refresh queue / devices",
            "?                toggle this help",
            "q                quit",
        ]
        h = len(lines) + 2
        w = max(len(l) for l in lines) + 4
        y0 = max(0, (self.height - h) // 2)
        x0 = max(0, (self.width - w) // 2)
        for y in range(h):
            safe_addstr(self.stdscr, y0 + y, x0, " " * w, self._color(2))
        for i, line in enumerate(lines):
            attr = self._color(2) | (curses.A_BOLD if i == 0 else curses.A_NORMAL)
            safe_addstr(self.stdscr, y0 + 1 + i, x0 + 2, line, attr)

    # ---- row sources --------------------------------------------------------
    def _current_rows(self) -> List[Row]:
        if self.tab_index == 0:
            return self._playlist_rows()
        if self.tab_index == 1:
            return self.search_rows
        if self.tab_index == 2:
            return self.queue_rows
        if self.tab_index == 3:
            self._rebuild_device_rows()
            return self.device_rows
        return []

    def _playlist_rows(self) -> List[Row]:
        if self.current_playlist is not None:
            rows = [Row("header", f"« {self.current_playlist['name']} (Backspace to go back)", selectable=False)]
            for t in self.current_playlist_tracks:
                if not t:
                    continue
                artists = ", ".join(a["name"] for a in t.get("artists", []))
                rows.append(Row("track", t.get("name", "Unknown"), artists, data=t))
            return rows
        rows = []
        for p in self.playlists:
            owner = (p.get("owner") or {}).get("display_name", "")
            count = (p.get("tracks") or {}).get("total", 0)
            rows.append(Row("playlist", p.get("name", "Unknown"), f"{count} tracks · {owner}", data=p))
        return rows

    def _rebuild_device_rows(self) -> None:
        with self.state.lock:
            devices = list(self.state.devices)
        rows = []
        for d in devices:
            marker = "● " if d.get("is_active") else "  "
            rows.append(
                Row(
                    "device",
                    f"{marker}{d.get('name', 'Unknown')}",
                    f"{d.get('type', '')} · vol {d.get('volume_percent', '?')}%",
                    data=d,
                )
            )
        self.device_rows = rows

    def _current_row(self) -> Optional[Row]:
        rows = self._current_rows()
        idx = self.selected[self.tab_index]
        if 0 <= idx < len(rows):
            return rows[idx]
        return None

    # ---- key handling -----------------------------------------------------
    def _handle_key(self, ch: int) -> bool:
        self.state.status = ""
        try:
            if self.show_help:
                if ch in (ord("?"), 27, ord("q")):
                    self.show_help = False
                return True

            if ch == ord("q"):
                return False
            if ch == ord("?"):
                self.show_help = True
            elif ch in (ord("1"), ord("2"), ord("3"), ord("4")):
                self._switch_tab(ch - ord("1"))
            elif ch == 9:
                self._switch_tab((self.tab_index + 1) % len(TABS))
            elif ch == curses.KEY_BTAB:
                self._switch_tab((self.tab_index - 1) % len(TABS))
            elif ch in (curses.KEY_DOWN, ord("j")):
                self._move_selection(1)
            elif ch in (curses.KEY_UP, ord("k")):
                self._move_selection(-1)
            elif ch == ord("g"):
                self.selected[self.tab_index] = 0
            elif ch == ord("G"):
                rows = self._current_rows()
                self.selected[self.tab_index] = max(0, len(rows) - 1)
            elif ch in (10, 13, curses.KEY_ENTER):
                self._activate_selection()
            elif ch in (curses.KEY_BACKSPACE, 127, 8, 27):
                self._go_back()
            elif ch in (ord(" "), ord("p")):
                self._toggle_play()
            elif ch == ord("n"):
                self._safe(self.client.next_track)
                self.state.status = "Skipped to next track."
            elif ch == ord("b"):
                self._safe(self.client.previous_track)
                self.state.status = "Went to previous track."
            elif ch in (ord("+"), ord("=")):
                self._adjust_volume(5)
            elif ch in (ord("-"), ord("_")):
                self._adjust_volume(-5)
            elif ch == ord("s"):
                self._toggle_shuffle()
            elif ch == ord("r"):
                self._cycle_repeat()
            elif ch == ord("a"):
                self._queue_selection()
            elif ch == ord("/"):
                self._open_search_prompt()
            elif ch == ord("R"):
                self._manual_refresh()
        except SpotifyError as exc:
            self.state.error = str(exc)
        return True

    def _safe(self, fn, *args, **kwargs) -> None:
        try:
            fn(*args, **kwargs)
            self.state.error = ""
        except SpotifyError as exc:
            self.state.error = str(exc)

    def _switch_tab(self, idx: int) -> None:
        self.tab_index = idx
        if idx == 2:
            self._manual_refresh()

    def _move_selection(self, delta: int) -> None:
        rows = self._current_rows()
        if not rows:
            return
        idx = self.selected[self.tab_index]
        n = len(rows)
        for _ in range(n):
            idx = (idx + delta) % n
            if rows[idx].selectable:
                break
        self.selected[self.tab_index] = idx

    def _go_back(self) -> None:
        if self.tab_index == 0 and self.current_playlist is not None:
            self.current_playlist = None
            self.current_playlist_tracks = []
            self.selected[0] = 0

    def _activate_selection(self) -> None:
        row = self._current_row()
        if row is None or not row.selectable:
            return
        if self.tab_index == 0:
            if self.current_playlist is None:
                self._open_playlist(row.data)
            else:
                self._play_playlist_track(row.data)
        elif self.tab_index == 1:
            self._play_search_result(row)
        elif self.tab_index == 3:
            self._switch_device(row.data)

    def _open_playlist(self, playlist: Dict[str, Any]) -> None:
        try:
            tracks = self.client.playlist_tracks(playlist["id"])
        except SpotifyError as exc:
            self.state.error = str(exc)
            return
        self.current_playlist = playlist
        self.current_playlist_tracks = tracks
        self.selected[0] = 1 if tracks else 0
        self.state.status = f"Opened playlist '{playlist.get('name')}'."

    def _play_playlist_track(self, track: Dict[str, Any]) -> None:
        if not track or self.current_playlist is None:
            return
        self._safe(self.client.play_context, self.current_playlist["uri"], track.get("uri"))
        self.state.status = f"Playing '{track.get('name')}'."

    def _play_search_result(self, row: Row) -> None:
        item = row.data
        if row.kind == "track":
            self._safe(self.client.play_uris, [item["uri"]])
        else:
            self._safe(self.client.play_context, item["uri"])
        self.state.status = f"Playing {row.kind} '{item.get('name')}'."

    def _switch_device(self, device: Dict[str, Any]) -> None:
        if not device:
            return
        self._safe(self.client.transfer_playback, device["id"])
        self.state.status = f"Switched playback to '{device.get('name')}'."

    def _toggle_play(self) -> None:
        with self.state.lock:
            playback = self.state.playback
        is_playing = bool(playback and playback.get("is_playing"))
        self._safe(self.client.play_pause, is_playing)
        self.state.status = "Paused." if is_playing else "Playing."
        with self.state.lock:
            if self.state.playback:
                self.state.playback["is_playing"] = not is_playing

    def _adjust_volume(self, delta: int) -> None:
        with self.state.lock:
            playback = self.state.playback
        current = (playback or {}).get("device", {}).get("volume_percent")
        if current is None:
            current = 50
        new_vol = max(0, min(100, current + delta))
        self._safe(self.client.set_volume, new_vol)
        self.state.status = f"Volume: {new_vol}%"

    def _toggle_shuffle(self) -> None:
        with self.state.lock:
            playback = self.state.playback
        current = bool(playback and playback.get("shuffle_state"))
        self._safe(self.client.toggle_shuffle, not current)
        self.state.status = f"Shuffle {'on' if not current else 'off'}."

    def _cycle_repeat(self) -> None:
        with self.state.lock:
            playback = self.state.playback
        current = (playback or {}).get("repeat_state", "off")
        idx = REPEAT_CYCLE.index(current) if current in REPEAT_CYCLE else 0
        new_state = REPEAT_CYCLE[(idx + 1) % len(REPEAT_CYCLE)]
        self._safe(self.client.set_repeat, new_state)
        self.state.status = REPEAT_LABEL[new_state]

    def _queue_selection(self) -> None:
        row = self._current_row()
        if row is None:
            return
        uri = None
        if self.tab_index in (0, 1) and row.kind == "track":
            uri = row.data.get("uri")
        if uri:
            self._safe(self.client.add_to_queue, uri)
            self.state.status = f"Added '{row.label}' to queue."
        else:
            self.state.status = "Nothing queueable selected."

    def _manual_refresh(self) -> None:
        if self.tab_index == 2:
            try:
                data = self.client.queue()
                self._rebuild_queue_rows(data)
                self.state.status = "Queue refreshed."
            except SpotifyError as exc:
                self.state.error = str(exc)
        else:
            self._refresh_devices()
            self.state.status = "Devices refreshed."

    def _rebuild_queue_rows(self, data: Dict[str, Any]) -> None:
        rows: List[Row] = []
        current = data.get("currently_playing")
        if current:
            artists = ", ".join(a["name"] for a in current.get("artists", []))
            rows.append(Row("header", "Now Playing", selectable=False))
            rows.append(Row("track", current.get("name", "Unknown"), artists, data=current, selectable=False))
        upcoming = data.get("queue", [])
        if upcoming:
            rows.append(Row("header", "Next Up", selectable=False))
            for t in upcoming:
                artists = ", ".join(a["name"] for a in t.get("artists", []))
                rows.append(Row("track", t.get("name", "Unknown"), artists, data=t, selectable=False))
        self.queue_rows = rows
        self.selected[2] = 0

    # ---- search prompt ------------------------------------------------------
    def _open_search_prompt(self) -> None:
        self.tab_index = 1
        query = self._prompt("Search: ", self.search_query)
        if query is None:
            return
        query = query.strip()
        if not query:
            return
        self.search_query = query
        try:
            results = self.client.search(query)
            self._rebuild_search_rows(results)
            self.state.status = f"Search results for '{query}'."
        except SpotifyError as exc:
            self.state.error = str(exc)

    def _rebuild_search_rows(self, results: Dict[str, Any]) -> None:
        rows: List[Row] = []

        tracks = (results.get("tracks") or {}).get("items", [])
        if tracks:
            rows.append(Row("header", "Tracks", selectable=False))
            for t in tracks:
                artists = ", ".join(a["name"] for a in t.get("artists", []))
                rows.append(Row("track", t.get("name", "Unknown"), artists, data=t))

        artists_ = (results.get("artists") or {}).get("items", [])
        if artists_:
            rows.append(Row("header", "Artists", selectable=False))
            for a in artists_:
                genres = ", ".join(a.get("genres", [])[:2])
                rows.append(Row("artist", a.get("name", "Unknown"), genres, data=a))

        albums = (results.get("albums") or {}).get("items", [])
        if albums:
            rows.append(Row("header", "Albums", selectable=False))
            for al in albums:
                artists = ", ".join(a["name"] for a in al.get("artists", []))
                rows.append(Row("album", al.get("name", "Unknown"), artists, data=al))

        playlists = (results.get("playlists") or {}).get("items", [])
        if playlists:
            rows.append(Row("header", "Playlists", selectable=False))
            for p in playlists:
                owner = (p.get("owner") or {}).get("display_name", "")
                rows.append(Row("playlist", p.get("name", "Unknown"), f"by {owner}", data=p))

        self.search_rows = rows
        self.selected[1] = next((i for i, r in enumerate(rows) if r.selectable), 0)

    def _prompt(self, label: str, initial: str = "") -> Optional[str]:
        curses.curs_set(1)
        text = list(initial)
        y = self.height - 1
        try:
            while True:
                safe_addstr(self.stdscr, y, 0, " " * self.width)
                prompt_text = label + "".join(text)
                safe_addstr(self.stdscr, y, 0, truncate(prompt_text, self.width - 1), self._color(3))
                try:
                    self.stdscr.move(y, min(self.width - 1, len(prompt_text)))
                except curses.error:
                    pass
                self.stdscr.refresh()
                self.stdscr.timeout(-1)
                ch = self.stdscr.getch()
                self.stdscr.timeout(250)
                if ch in (10, 13, curses.KEY_ENTER):
                    return "".join(text)
                if ch == 27:
                    return None
                if ch in (curses.KEY_BACKSPACE, 127, 8):
                    if text:
                        text.pop()
                    continue
                if 32 <= ch <= 126:
                    text.append(chr(ch))
        finally:
            curses.curs_set(0)


def run() -> None:
    print("Connecting to Spotify…")
    try:
        client = Client()
    except Exception as exc:  # noqa: BLE001 - surface any startup failure clearly
        print(f"Failed to initialize Spotify client: {exc}")
        raise SystemExit(1)

    def _start(stdscr):
        App(stdscr, client).main_loop()

    curses.wrapper(_start)
