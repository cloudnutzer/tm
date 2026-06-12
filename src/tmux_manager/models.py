from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class TmuxSession:
    name: str
    windows: int
    attached: int
    activity: int
    path: str
    created: int


@dataclass(frozen=True)
class PostAction:
    """What cli.main() should do after the TUI has shut down."""

    kind: Literal["attach", "switch"]
    target: str


@dataclass(frozen=True)
class NewSessionRequest:
    name: str
    start_dir: str | None = None
