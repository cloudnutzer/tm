from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class TmuxSession:
    name: str
    windows: int
    attached: int
    """Number of clients currently attached."""
    activity: int
    """Epoch seconds of the last activity in the session."""
    path: str
    """Directory the session was started in."""
    current_path: str
    """Working directory of the active pane."""
    command: str
    """Foreground command of the active pane."""


@dataclass(frozen=True)
class TmuxPane:
    session: str
    window_index: int
    window_name: str
    pane_index: int
    pane_id: str
    """tmux pane id such as ``%12``; stable for the lifetime of the pane."""
    pane_pid: int
    """PID of the process tmux started in the pane (usually a shell)."""
    command: str
    """Foreground command as tmux sees it (``2.1.281`` for Claude Code)."""
    current_path: str
    window_activity: int
    """Epoch seconds of the last output in the pane's window."""
    window_panes: int
    """Number of panes in the pane's window."""
    title: str
    """Pane title set by the program via OSC 0/2 (``✳ Claude Code``)."""
    agent: str | None = None
    """Manifest id of the coding agent running in the pane, if any."""


@dataclass(frozen=True)
class PostAction:
    """What cli.main() should do after the TUI has shut down."""

    kind: Literal["attach", "switch"]
    target: str


@dataclass(frozen=True)
class NewSessionRequest:
    name: str
    start_dir: str | None = None
