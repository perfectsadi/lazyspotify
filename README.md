# lazyspotify

A `lazygit`-style terminal UI for Spotify, built with Python's `curses` and
the Spotify Web API (`spotipy`). Requires Spotify **Premium** for playback
control (the Web API can't control playback on free accounts), and an
already-open Spotify app/device (desktop, mobile, or web player) to play
through.

## Install

```bash
pip install -r requirements.txt
# or, for the `lazyspotify` console command:
pip install -e .
```

## Credentials

Since you already have a Spotify Developer app, just make sure its
**Redirect URI** (in the app's "Edit Settings" on the
[developer dashboard](https://developer.spotify.com/dashboard)) includes:

```
http://127.0.0.1:8080/callback
```

Then give lazyspotify your Client ID / Secret one of two ways:

**Environment variables** (recommended for shells/dotfiles):

```bash
export SPOTIPY_CLIENT_ID="your-client-id"
export SPOTIPY_CLIENT_SECRET="your-client-secret"
export SPOTIPY_REDIRECT_URI="http://127.0.0.1:8080/callback"  # optional, this is the default
```

**Or** just run it — if no env vars are found, it'll prompt you once and
save the values to `~/.config/lazyspotify/config.ini` (permissions `600`)
for next time.

The OAuth token itself is cached at `~/.config/lazyspotify/.spotify-token-cache`.
First run opens a browser to authorize; after that it's silent.

## Run

```bash
python -m lazyspotify
# or, if installed with `pip install -e .`:
lazyspotify
```

## Layout

```
┌ lazyspotify ───┬──────────────────────────────────────┐
│ 1. Playlists   │  (selected tab's content here)        │
│ 2. Search      │                                        │
│ 3. Queue       │                                        │
│ 4. Devices     │                                        │
│                │                                        │
├────────────────┴──────────────────────────────────────┤
│ ▶  Track Name — Artist                                  │
│ ████████████████──────────────  1:23/3:45               │
│ Shuffle: off   Repeat: Off   Vol: 70%   Device: My Laptop│
├──────────────────────────────────────────────────────────┤
│ status / error line                                       │
└──────────────────────────────────────────────────────────┘
```

## Keybindings

| Key             | Action                          |
|-----------------|----------------------------------|
| `1`–`4` / `Tab`  | Switch panel                    |
| `j`/`k`, `↑`/`↓` | Move selection                  |
| `g` / `G`        | Jump to top / bottom            |
| `Enter`          | Play / open selection           |
| `Backspace`/`Esc`| Go back (e.g. out of a playlist)|
| `Space` or `p`   | Play / pause                    |
| `n` / `b`        | Next / previous track           |
| `+` / `-`        | Volume up / down (5%)           |
| `s`              | Toggle shuffle                  |
| `r`              | Cycle repeat mode (off→all→one) |
| `a`              | Add selected track to queue     |
| `/`              | Search                          |
| `R`              | Refresh queue / devices         |
| `?`              | Toggle help                     |
| `q`              | Quit                            |

### Panels

- **Playlists** — browse your playlists; `Enter` opens one, `Enter` on a
  track plays the playlist from there.
- **Search** — `/` to search tracks, artists, albums, and playlists at
  once; `Enter` plays the selection, `a` queues a track.
- **Queue** — read-only view of what's currently playing and next up;
  press `R` to refresh (it's not auto-polled, to limit API calls).
- **Devices** — see your active Spotify devices; `Enter` transfers
  playback to the selected one.

## Notes

- Playback state is polled every 3 seconds in the background; the
  progress bar interpolates between polls so it stays smooth.
- If nothing happens when you hit play, make sure a Spotify client
  (desktop/mobile/web) is open somewhere — the Web API needs an active
  device to play through, it doesn't play audio itself.
- Built with the standard library `curses` module, so there are no GUI
  dependencies — just `spotipy` for the API calls.
