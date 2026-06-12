# tmux-manager (`tm`)

An interactive terminal UI for managing tmux sessions. One command — `tm` —
replaces the usual `tmux ls` → `tmux attach`/`tmux new` dance with a
keyboard-driven session overview: attach, create, kill, rename, detach
clients, watch a live preview of what's running in each session, and jump
into project directories via a built-in sessionizer.

```
┌─ tmux manager ───────────────────────────────────────────────┐
│ Name        Win  Att  Activity  Path        │ Preview         │
│ ▶ work       3    ●     now     ~/work      │ $ npm run dev   │
│   dotfiles   1          2h      ~/.dotfiles │ > server        │
│   scratch    2          5d      ~           │   listening on  │
│                                             │   :3000 ...     │
├──────────────────────────────────────────────────────────────┤
│ n new  d delete  r rename  D detach  p projects  / filter  q │
└──────────────────────────────────────────────────────────────┘
```

Built with [Textual](https://textual.textualize.io/). Works inside and
outside of tmux — outside it attaches to the chosen session, inside it
switches the current client.

---

## Requirements

| Dependency | Version | Notes |
|---|---|---|
| tmux | any recent version (tested with 3.6a) | must be on `PATH` |
| Python | ≥ 3.11 | uses stdlib `tomllib` |
| Textual | ≥ 1.0 | installed automatically |

macOS and Linux are supported (anywhere tmux runs).

## Quick Start

```bash
# 1. Get the code
git clone https://github.com/cloudnutzer/tm.git
cd tm

# 2. Install into a local virtualenv
python3 -m venv .venv
.venv/bin/pip install -e .

# 3. Put the `tm` command on your PATH
mkdir -p ~/.local/bin
ln -s "$PWD/.venv/bin/tm" ~/.local/bin/tm

# 4. Make sure ~/.local/bin is on your PATH (add to ~/.zshrc if missing)
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc && exec zsh

# 5. Run it
tm
```

That's it. You'll see all running tmux sessions (or an empty state if none
exist — press `n` to create your first one). Move with `j`/`k` or the arrow
keys and hit `Enter` to jump into a session.

> **Tip:** the install is *editable* — if you pull or edit the code, the
> `tm` command picks up changes immediately, no reinstall needed.

### Your first 60 seconds

1. `tm` — the session list opens; the right pane shows a live preview of
   whatever is running in the highlighted session.
2. Press `n`, type a name (e.g. `scratch`), `Enter` — a new session is
   created and you land directly inside it.
3. Detach from tmux as usual (`prefix d`), run `tm` again — your session is
   in the list, press `Enter` to get back in.
4. Press `p` — every directory under `~/git-projects` shows up. Pick one and
   you get a session named after the project, started in that directory.
   Pick it again later and you jump back into the existing session (marked
   with `●`).

## Key Bindings

### Session list (main screen)

| Key | Action |
|---|---|
| `j` / `k` / `↓` / `↑` | move the cursor |
| `Enter` | attach to session (outside tmux) / switch client (inside tmux) |
| `n` | create a new session — asks for a name and an optional start directory |
| `d` | kill the selected session (asks for confirmation; warns if it's the session you're currently in) |
| `r` | rename the selected session |
| `D` | detach all clients from the selected session — handy when a session is "attached" on another terminal |
| `p` | open the project sessionizer |
| `/` | filter the session list as you type (`Esc` clears, `Enter` jumps to the match) |
| `q` / `Esc` | quit |

### Project sessionizer (`p`)

| Key | Action |
|---|---|
| `j` / `k` / `↓` / `↑` | move the cursor |
| `Enter` | create a session for the project (or attach if it already exists, marked `●`) |
| `Esc` / `q` | back to the session list |

### Dialogs

| Key | Action |
|---|---|
| `y` / `n` | confirm / decline (kill & detach confirmations) |
| `Enter` | submit input dialogs |
| `Esc` | cancel any dialog |

## Features in Detail

### Session overview with live preview

The table shows every session with its window count, an `●` attached
indicator, relative last-activity time (`now`, `3m`, `2h`, `5d`) and its
working directory. Both the list and the preview refresh every 2 seconds,
so sessions created or killed from other terminals appear automatically.
The preview renders the actual terminal content (including colors) of the
highlighted session's active pane — you can see whether a dev server is
still running before you attach.

### Attach vs. switch

`tm` detects where it runs:

- **Outside tmux** → the TUI exits cleanly, then `exec`s
  `tmux attach-session`, so `tm` leaves no extra process behind.
- **Inside tmux** (`$TMUX` set) → it issues `tmux switch-client`, so your
  current client jumps to the chosen session.

### Project sessionizer

Press `p` to list the subdirectories of your configured project roots
(default: `~/git-projects`). Selecting a project:

1. derives a session name from the directory name (tmux-illegal characters
   `.` and `:` become `_`),
2. creates the session **in that directory** if it doesn't exist yet,
3. attaches/switches to it.

Existing project sessions are marked with `●`, and selecting them never
creates duplicates. Hidden directories (starting with `.`) are skipped.

### Safe by construction

- All tmux calls use argv lists (never a shell), so session names and paths
  with spaces just work.
- Session targets use tmux's exact-match prefix (`=name`), so `work` never
  accidentally matches `work-2`.
- Destructive actions (kill, detach) always ask first. Killing the session
  you're currently inside shows an extra warning.
- If no tmux server is running, `tm` shows an empty state instead of an
  error — `n` and `p` still work and start the server for you.

## Configuration

Optional. Create `~/.config/tmux-manager/config.toml`
(`$XDG_CONFIG_HOME` is respected). Every key is optional; these are the
defaults:

```toml
[projects]
# Directories whose subdirectories appear in the sessionizer (p).
# Multiple roots are allowed; ~ is expanded.
roots = ["~/git-projects"]

[sessions]
# Pre-filled start directory for new sessions (n).
default_dir = "~"

[ui]
# Refresh intervals in seconds.
list_refresh_seconds = 2.0
preview_refresh_seconds = 2.0
```

Example with several project roots:

```toml
[projects]
roots = ["~/git-projects", "~/work/repos", "/srv/projects"]
```

## Optional: open `tm` as a tmux popup

Add this to your `~/.tmux.conf` to summon the manager as a floating popup
over your current session with `prefix + S`:

```tmux
bind S display-popup -E -w 80% -h 75% tm
```

Selecting a session inside the popup switches your client and closes the
popup — a very fast way to hop between sessions without leaving tmux.

## Troubleshooting

- **`tm: command not found`** — `~/.local/bin` is not on your `PATH`, or
  the symlink is missing. Re-run steps 3–4 of the Quick Start.
- **A session refuses to attach ("session is attached elsewhere")** — select
  it and press `D` to detach the other client first.
- **My session is named `my_project` instead of `my.project`** — tmux
  forbids `.` and `:` in session names; `tm` replaces them with `_`.
- **The preview is empty** — the session's active pane may simply have a
  blank screen; the preview shows exactly what `tmux capture-pane` returns.

## Development

### Project layout

```
src/tmux_manager/
├── cli.py               # entry point: runs the app, then attaches/switches
├── app.py               # Textual App, pushes the main screen
├── tmux.py              # the ONLY place that shells out to tmux (testable seam)
├── config.py            # config.toml loading (stdlib tomllib)
├── models.py            # TmuxSession, PostAction, NewSessionRequest dataclasses
├── util.py              # path shortening, relative time formatting
├── styles.tcss          # Textual CSS
└── screens/
    ├── sessions.py      # main screen: table + preview + filter
    ├── sessionizer.py   # project picker
    └── modals.py        # new/rename/confirm dialogs
```

Two design decisions worth knowing before hacking on it:

1. **Attach-on-exit:** the TUI never execs tmux itself (the terminal would
   still be in alternate-screen mode). Instead the app exits with a
   `PostAction` result and `cli.main()` performs the attach/switch after
   Textual has restored the terminal.
2. **`tmux.py` is the only subprocess boundary.** Everything else is pure
   Python, which keeps the TUI fully testable with fakes. The `TM_SOCKET`
   environment variable routes every tmux call to an isolated server
   (`tmux -L <socket>`) so tests never touch your real sessions.

### Running the tests

```bash
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
```

This covers the tmux wrapper (argv construction, output parsing, error
handling) and the TUI itself via Textual's headless test pilot (navigation,
attach/switch results, filtering, empty state).

### Manual end-to-end testing

Run against a throwaway tmux server — your real sessions stay untouched:

```bash
export TM_SOCKET=tmtest
tmux -L tmtest new-session -d -s demo-1 -c /tmp
tmux -L tmtest new-session -d -s demo-2 -c ~
tmux -L tmtest send-keys -t demo-2 'echo hello-preview' Enter

tm    # play with the UI against the isolated server

tmux -L tmtest kill-server
unset TM_SOCKET
```

Note: if you run this from a shell that is itself inside tmux, `Enter`
performs a *switch* (not an attach) — that's the expected behavior.

## Roadmap ideas

Not implemented yet, collected during planning:

- Session templates: predefined window layouts (editor / server / logs) for new sessions
- Save & restore session setups across reboots
- Search windows across all sessions and jump straight to one
- Bulk cleanup: kill all detached sessions older than X
- Toggle back to the previous session with one key
- Git branch / dirty status per project in the sessionizer; zoxide as an additional project source
- Non-interactive subcommands for scripting (`tm new foo`, `tm kill foo`, `tm ls --json`)
- Activity/bell indicators and the foreground process per session in the list
