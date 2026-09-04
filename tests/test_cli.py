import pytest

from tmux_manager import __version__, cli
from tmux_manager.config import Config, ConfigError
from tmux_manager.models import PostAction


def test_version_flag_prints_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.build_parser().parse_args(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_help_flag_lists_key_bindings(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.build_parser().parse_args(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "sessionizer" in out
    assert "attach" in out


def test_unknown_argument_fails() -> None:
    with pytest.raises(SystemExit) as exc:
        cli.build_parser().parse_args(["--bogus"])
    assert exc.value.code != 0


@pytest.fixture
def cli_env(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, list[str]]]:
    execs: list[tuple[str, list[str]]] = []
    monkeypatch.delenv("TM_SOCKET", raising=False)
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/tmux")
    monkeypatch.setattr(cli, "load_config", lambda: Config())
    monkeypatch.setattr(cli.os, "execvp", lambda file, args: execs.append((file, args)))
    return execs


def test_main_execs_attach_after_tui(
    cli_env: list[tuple[str, list[str]]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "run_tui", lambda config: PostAction(kind="attach", target="work"))
    cli.main([])
    assert cli_env == [("tmux", ["tmux", "attach-session", "-t", "=work"])]


def test_main_switches_client_inside_tmux(
    cli_env: list[tuple[str, list[str]]], monkeypatch: pytest.MonkeyPatch
) -> None:
    switched: list[str] = []
    monkeypatch.setattr(cli.tmux, "switch_client", switched.append)
    monkeypatch.setattr(cli, "run_tui", lambda config: PostAction(kind="switch", target="work"))
    cli.main([])
    assert switched == ["work"]
    assert cli_env == []


def test_main_does_nothing_when_tui_quits(
    cli_env: list[tuple[str, list[str]]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "run_tui", lambda config: None)
    cli.main([])
    assert cli_env == []


def test_main_fails_without_tmux(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)
    with pytest.raises(SystemExit) as exc:
        cli.main([])
    assert exc.value.code == 1
    assert "tmux not found" in capsys.readouterr().err


def test_main_reports_config_errors(
    cli_env: list[tuple[str, list[str]]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def broken() -> Config:
        raise ConfigError("ui.sort must be one of name, activity")

    monkeypatch.setattr(cli, "load_config", broken)
    with pytest.raises(SystemExit) as exc:
        cli.main([])
    assert exc.value.code == 2
    assert "config error: ui.sort" in capsys.readouterr().err
