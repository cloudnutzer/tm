"""All tmux subprocess calls live here — the single testable seam.

Conventions:
- argv lists only, never shell=True, so names/paths with spaces are safe
- session targets always use the ``=`` prefix to force exact-name matching
- ``TM_SOCKET`` env var routes everything to ``tmux -L <socket>`` so tests
  and experiments can run against an isolated server
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import replace

from .models import PostAction, TmuxPane, TmuxSession

# \x1f (ASCII unit separator) cannot appear in session names or paths,
# so splitting on it is unambiguous.
LIST_FORMAT = "\x1f".join(
    (
        "#{session_name}",
        "#{session_windows}",
        "#{session_attached}",
        "#{session_activity}",
        "#{session_path}",
        "#{pane_current_path}",
        "#{pane_current_command}",
    )
)

PANE_FORMAT = "\x1f".join(
    (
        "#{session_name}",
        "#{window_index}",
        "#{window_name}",
        "#{pane_index}",
        "#{pane_id}",
        "#{pane_pid}",
        "#{pane_current_command}",
        "#{pane_current_path}",
        "#{window_activity}",
        "#{window_panes}",
        # last: a title is set by the program and could contain anything
        "#{pane_title}",
    )
)
# Global flag placed before the command: without it tmux replaces non-ASCII
# characters in formats and captures by "_" when the locale is not UTF-8
# (e.g. under launchd), and agent titles such as "✳ Claude Code" get lost.
UTF8 = "-u"

_NO_SERVER_MARKERS = ("no server running", "error connecting to")
# e.g. "bind-key -T prefix S display-popup -E -w 80% -h 75% tm"
_POPUP_BINDING = re.compile(r"-T prefix\s+(\S+)\s+display-popup\b.*\btm\b")


class TmuxError(RuntimeError):
    pass


def base_argv() -> list[str]:
    argv = ["tmux"]
    socket = os.environ.get("TM_SOCKET")
    if socket:
        argv += ["-L", socket]
    return argv


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(base_argv() + args, capture_output=True, text=True, check=False)
    except FileNotFoundError as error:
        raise TmuxError("tmux not found on PATH") from error


def _run_or_raise(args: list[str]) -> str:
    result = _run(args)
    if result.returncode != 0:
        raise TmuxError(result.stderr.strip() or f"tmux {args[0]} failed")
    return result.stdout


def inside_tmux() -> bool:
    return bool(os.environ.get("TMUX"))


def sanitize_session_name(raw: str) -> str:
    # tmux forbids "." and ":" in session names (they are target separators),
    # and a leading "-" would be parsed as a command flag.
    name = raw.strip().replace(".", "_").replace(":", "_")
    if name.startswith("-"):
        name = "_" + name[1:]
    if not name:
        raise ValueError("session name is empty")
    return name


def attach_action(name: str) -> PostAction:
    """Switch the current client when inside tmux, otherwise attach."""
    return PostAction(kind="switch" if inside_tmux() else "attach", target=name)


def pane_action(pane: TmuxPane) -> PostAction:
    """Like attach_action, but land in exactly this pane."""
    return replace(attach_action(pane.session), pane=pane.pane_id)


def list_sessions() -> list[TmuxSession]:
    result = _run(["list-sessions", "-F", LIST_FORMAT])
    if result.returncode != 0:
        stderr = result.stderr.strip()
        if any(marker in stderr for marker in _NO_SERVER_MARKERS):
            return []
        raise TmuxError(stderr or "tmux list-sessions failed")
    sessions = []
    for line in result.stdout.splitlines():
        if not line:
            continue
        name, windows, attached, activity, path, current_path, command = line.split("\x1f")
        sessions.append(
            TmuxSession(
                name=name,
                windows=int(windows),
                attached=int(attached),
                activity=int(activity),
                path=path,
                current_path=current_path,
                command=command,
            )
        )
    return sessions


def list_panes() -> list[TmuxPane]:
    """Every pane of every session."""
    result = _run([UTF8, "list-panes", "-a", "-F", PANE_FORMAT])
    if result.returncode != 0:
        stderr = result.stderr.strip()
        if any(marker in stderr for marker in _NO_SERVER_MARKERS):
            return []
        raise TmuxError(stderr or "tmux list-panes failed")
    panes = []
    # split("\n"), not splitlines(): titles may contain other line breaks
    for line in result.stdout.split("\n"):
        if not line:
            continue
        fields = line.split("\x1f", 10)
        session, window, window_name, pane, pane_id, pid, command, path, activity = fields[:9]
        panes.append(
            TmuxPane(
                session=session,
                window_index=int(window),
                window_name=window_name,
                pane_index=int(pane),
                pane_id=pane_id,
                pane_pid=int(pid or 0),
                command=command,
                current_path=path,
                window_activity=int(activity or 0),
                window_panes=int(fields[9] or 1),
                title=fields[10],
            )
        )
    return panes


def new_session(name: str, start_dir: str | None = None) -> None:
    args = ["new-session", "-d", "-s", name]
    if start_dir:
        args += ["-c", start_dir]
    _run_or_raise(args)


def kill_session(name: str) -> None:
    _run_or_raise(["kill-session", "-t", f"={name}"])


def rename_session(old: str, new: str) -> None:
    _run_or_raise(["rename-session", "-t", f"={old}", new])


def detach_clients(name: str) -> None:
    _run_or_raise(["detach-client", "-s", f"={name}"])


def capture_pane(name: str) -> str:
    # Pane targets need the trailing ":" so "=name" is parsed as an exact
    # session match; the active pane of the current window is then used.
    return _run_or_raise(["capture-pane", "-ep", "-t", f"={name}:"])


def capture_pane_by_id(pane_id: str, *, colors: bool = False) -> str:
    """Visible text of one pane (``%12``); with ``colors`` including ANSI escapes."""
    return _run_or_raise([UTF8, "capture-pane", "-ep" if colors else "-p", "-t", pane_id])


def has_session(name: str) -> bool:
    return _run(["has-session", "-t", f"={name}"]).returncode == 0


def select_pane(pane_id: str) -> None:
    """Make the pane the current one of its window, and its window current."""
    _run_or_raise(["select-window", "-t", pane_id])
    _run_or_raise(["select-pane", "-t", pane_id])


def switch_client(name: str) -> None:
    _run_or_raise(["switch-client", "-t", f"={name}"])


def popup_binding() -> str | None:
    """The prefix key bound to a display-popup that runs tm, if any."""
    result = _run(["list-keys", "-T", "prefix"])
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        match = _POPUP_BINDING.search(line)
        if match:
            return match.group(1)
    return None


def current_session() -> str | None:
    if not inside_tmux():
        return None
    result = _run(["display-message", "-p", "#{session_name}"])
    if result.returncode != 0:
        return None
    return result.stdout.strip()
