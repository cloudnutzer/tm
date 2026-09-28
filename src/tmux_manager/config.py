from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

DEFAULT_PROJECT_ROOTS = (Path("~/git-projects").expanduser(),)
MIN_REFRESH_SECONDS = 0.2
MIN_GRACE_SECONDS = 0.5
SORT_MODES = ("name", "activity")

SortMode = Literal["name", "activity"]


class ConfigError(Exception):
    """The config file exists but cannot be used."""


@dataclass(frozen=True)
class Config:
    project_roots: tuple[Path, ...] = DEFAULT_PROJECT_ROOTS
    default_dir: str = "~"
    list_refresh_seconds: float = 2.0
    preview_refresh_seconds: float = 2.0
    show_preview: bool = True
    preview_width: int = 40
    """Width of the preview pane in percent of the terminal width."""
    sort: SortMode = "name"
    working_grace_seconds: float = 3.0
    """An agent whose pane changed within this many seconds counts as working."""


def config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME", "~/.config")
    return Path(base).expanduser() / "tmux-manager" / "config.toml"


def load_config(path: Path | None = None) -> Config:
    path = path or config_path()
    if not path.is_file():
        return Config()
    try:
        data = tomllib.loads(path.read_text())
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ConfigError(f"{path}: {error}") from error
    return parse_config(data)


def parse_config(data: dict[str, Any]) -> Config:
    defaults = Config()
    projects = _table(data, "projects")
    sessions = _table(data, "sessions")
    ui = _table(data, "ui")
    agents = _table(data, "agents")

    raw_roots = projects.get("roots", [])
    if not isinstance(raw_roots, list) or not all(isinstance(r, str) for r in raw_roots):
        raise ConfigError("projects.roots must be a list of strings")
    roots = tuple(Path(root).expanduser() for root in raw_roots) or defaults.project_roots

    sort = _string(ui, "sort", defaults.sort)
    if sort not in SORT_MODES:
        raise ConfigError(f"ui.sort must be one of {', '.join(SORT_MODES)}")

    preview_width = _number(ui, "preview_width", defaults.preview_width, minimum=10)
    if preview_width > 90:
        raise ConfigError("ui.preview_width must be at most 90")

    return Config(
        project_roots=roots,
        default_dir=_string(sessions, "default_dir", defaults.default_dir),
        list_refresh_seconds=_number(
            ui, "list_refresh_seconds", defaults.list_refresh_seconds, minimum=MIN_REFRESH_SECONDS
        ),
        preview_refresh_seconds=_number(
            ui,
            "preview_refresh_seconds",
            defaults.preview_refresh_seconds,
            minimum=MIN_REFRESH_SECONDS,
        ),
        show_preview=_bool(ui, "show_preview", defaults.show_preview),
        preview_width=int(preview_width),
        sort=sort,  # type: ignore[arg-type]  # validated against SORT_MODES above
        working_grace_seconds=_number(
            agents,
            "working_grace_seconds",
            defaults.working_grace_seconds,
            minimum=MIN_GRACE_SECONDS,
        ),
    )


def _table(data: dict[str, Any], name: str) -> dict[str, Any]:
    section = data.get(name, {})
    if not isinstance(section, dict):
        raise ConfigError(f"[{name}] must be a table")
    return section


def _string(section: dict[str, Any], key: str, default: str) -> str:
    value = section.get(key, default)
    if not isinstance(value, str):
        raise ConfigError(f"{key} must be a string")
    return value


def _bool(section: dict[str, Any], key: str, default: bool) -> bool:
    value = section.get(key, default)
    if not isinstance(value, bool):
        raise ConfigError(f"{key} must be true or false")
    return value


def _number(section: dict[str, Any], key: str, default: float, *, minimum: float) -> float:
    value = section.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ConfigError(f"{key} must be a number")
    if value < minimum:
        raise ConfigError(f"{key} must be at least {minimum}")
    return float(value)
