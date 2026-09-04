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
class PostAction:
    """What cli.main() should do after the TUI has shut down."""

    kind: Literal["attach", "switch"]
    target: str


@dataclass(frozen=True)
class NewSessionRequest:
    name: str
    start_dir: str | None = None
