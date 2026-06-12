from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PROJECT_ROOTS = (Path("~/git-projects").expanduser(),)


@dataclass(frozen=True)
class Config:
    project_roots: tuple[Path, ...] = DEFAULT_PROJECT_ROOTS
    default_dir: str = "~"
    list_refresh_seconds: float = 2.0
    preview_refresh_seconds: float = 2.0


def config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME", "~/.config")
    return Path(base).expanduser() / "tmux-manager" / "config.toml"


def load_config(path: Path | None = None) -> Config:
    path = path or config_path()
    if not path.is_file():
        return Config()
    data = tomllib.loads(path.read_text())
    projects = data.get("projects", {})
    sessions = data.get("sessions", {})
    ui = data.get("ui", {})
    defaults = Config()
    roots = (
        tuple(Path(root).expanduser() for root in projects.get("roots", []))
        or defaults.project_roots
    )
    return Config(
        project_roots=roots,
        default_dir=sessions.get("default_dir", defaults.default_dir),
        list_refresh_seconds=float(ui.get("list_refresh_seconds", defaults.list_refresh_seconds)),
        preview_refresh_seconds=float(
            ui.get("preview_refresh_seconds", defaults.preview_refresh_seconds)
        ),
    )
