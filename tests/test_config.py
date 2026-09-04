from pathlib import Path

import pytest

from tmux_manager.config import Config, ConfigError, load_config


def test_missing_file_gives_defaults(tmp_path: Path) -> None:
    cfg = load_config(tmp_path / "nope.toml")
    assert cfg == Config()
    assert cfg.project_roots == (Path("~/git-projects").expanduser(),)
    assert cfg.list_refresh_seconds == 2.0
    assert cfg.show_preview is True
    assert cfg.sort == "name"


def test_load_full_config(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        '[projects]\nroots = ["~/code", "/srv/projects"]\n'
        '[sessions]\ndefault_dir = "~/code"\n'
        "[ui]\nlist_refresh_seconds = 5\nshow_preview = false\n"
        'preview_width = 50\nsort = "activity"\n'
    )
    cfg = load_config(path)
    assert cfg.project_roots == (Path("~/code").expanduser(), Path("/srv/projects"))
    assert cfg.default_dir == "~/code"
    assert cfg.list_refresh_seconds == 5.0
    assert cfg.preview_refresh_seconds == 2.0
    assert cfg.show_preview is False
    assert cfg.preview_width == 50
    assert cfg.sort == "activity"


def test_partial_config_keeps_other_defaults(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('[sessions]\ndefault_dir = "/tmp"\n')
    cfg = load_config(path)
    assert cfg.default_dir == "/tmp"
    assert cfg.project_roots == Config().project_roots


def test_invalid_toml_is_a_config_error(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[projects\nroots = [")
    with pytest.raises(ConfigError, match=str(path)):
        load_config(path)


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ('[projects]\nroots = "~/code"\n', "projects.roots must be a list"),
        ("[projects]\nroots = [1, 2]\n", "projects.roots must be a list"),
        ("[sessions]\ndefault_dir = 3\n", "default_dir must be a string"),
        ("[ui]\nlist_refresh_seconds = 0\n", "list_refresh_seconds must be at least"),
        ("[ui]\npreview_refresh_seconds = -1\n", "preview_refresh_seconds must be at least"),
        ('[ui]\nlist_refresh_seconds = "fast"\n', "list_refresh_seconds must be a number"),
        ("[ui]\nlist_refresh_seconds = true\n", "list_refresh_seconds must be a number"),
        ('[ui]\nshow_preview = "yes"\n', "show_preview must be true or false"),
        ('[ui]\nsort = "size"\n', "ui.sort must be one of"),
        ("[ui]\npreview_width = 95\n", "preview_width must be at most 90"),
        ("[ui]\npreview_width = 5\n", "preview_width must be at least"),
        ('ui = "nope"\n', r"\[ui\] must be a table"),
    ],
)
def test_invalid_values_are_config_errors(tmp_path: Path, content: str, message: str) -> None:
    path = tmp_path / "config.toml"
    path.write_text(content)
    with pytest.raises(ConfigError, match=message):
        load_config(path)
