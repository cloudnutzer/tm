"""All tmux subprocess calls live here — the single testable seam.

Conventions:
- argv lists only, never shell=True, so names/paths with spaces are safe
- session targets always use the ``=`` prefix to force exact-name matching
- ``TM_SOCKET`` env var routes everything to ``tmux -L <socket>`` so tests
  and experiments can run against an isolated server
"""

from __future__ import annotations

import os
import subprocess

from .models import TmuxSession

# \x1f (ASCII unit separator) cannot appear in session names or paths,
# so splitting on it is unambiguous.
LIST_FORMAT = "\x1f".join(
    (
        "#{session_name}",
        "#{session_windows}",
        "#{session_attached}",
        "#{session_activity}",
        "#{session_path}",
        "#{session_created}",
    )
)

_NO_SERVER_MARKERS = ("no server running", "error connecting to")


class TmuxError(RuntimeError):
    pass


def base_argv() -> list[str]:
    argv = ["tmux"]
    socket = os.environ.get("TM_SOCKET")
    if socket:
        argv += ["-L", socket]
    return argv


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(base_argv() + args, capture_output=True, text=True, check=False)


def _run_or_raise(args: list[str]) -> str:
    result = _run(args)
    if result.returncode != 0:
        raise TmuxError(result.stderr.strip() or f"tmux {args[0]} failed")
    return result.stdout


def inside_tmux() -> bool:
    return bool(os.environ.get("TMUX"))


def sanitize_session_name(raw: str) -> str:
    # tmux forbids "." and ":" in session names (they are target separators)
    name = raw.strip().replace(".", "_").replace(":", "_")
    if not name:
        raise ValueError("session name is empty")
    return name


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
        name, windows, attached, activity, path, created = line.split("\x1f")
        sessions.append(
            TmuxSession(
                name=name,
                windows=int(windows),
                attached=int(attached),
                activity=int(activity),
                path=path,
                created=int(created),
            )
        )
    return sessions


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


def has_session(name: str) -> bool:
    return _run(["has-session", "-t", f"={name}"]).returncode == 0


def switch_client(name: str) -> None:
    _run_or_raise(["switch-client", "-t", f"={name}"])


def current_session() -> str | None:
    if not inside_tmux():
        return None
    result = _run(["display-message", "-p", "#{session_name}"])
    if result.returncode != 0:
        return None
    return result.stdout.strip()
