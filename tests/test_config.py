from pathlib import Path

from tmux_manager.config import Config, load_config


def test_missing_file_gives_defaults(tmp_path):
    cfg = load_config(tmp_path / "nope.toml")
    assert cfg == Config()
    assert cfg.project_roots == (Path("~/git-projects").expanduser(),)
    assert cfg.list_refresh_seconds == 2.0


def test_load_full_config(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[projects]\nroots = ["~/code", "/srv/projects"]\n'
        '[sessions]\ndefault_dir = "~/code"\n'
        "[ui]\nlist_refresh_seconds = 5\n"
    )
    cfg = load_config(path)
    assert cfg.project_roots == (Path("~/code").expanduser(), Path("/srv/projects"))
    assert cfg.default_dir == "~/code"
    assert cfg.list_refresh_seconds == 5.0
    assert cfg.preview_refresh_seconds == 2.0


def test_partial_config_keeps_other_defaults(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[sessions]\ndefault_dir = "/tmp"\n')
    cfg = load_config(path)
    assert cfg.default_dir == "/tmp"
    assert cfg.project_roots == Config().project_roots
