import json
from pathlib import Path

import pytest

from tmux_manager import __version__, cli
from tmux_manager.config import Config, ConfigError
from tmux_manager.models import PostAction

from .conftest import CLAUDE_TRUST, FakeTmux, make_pane


def test_version_flag_prints_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.build_parser().parse_args(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_help_flag_lists_commands_and_keys(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.build_parser().parse_args(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "sessionizer" in out
    assert "tm ls [--json]" in out
    assert "tm kill NAME" in out
    assert "tm agents [--json]" in out
    assert "tm status [--ascii]" in out
    assert "agents: coding agents" in out


def test_unknown_argument_fails() -> None:
    with pytest.raises(SystemExit) as exc:
        cli.build_parser().parse_args(["--bogus"])
    assert exc.value.code != 0


def test_normalize_argv_inserts_open() -> None:
    assert cli.normalize_argv([]) == []
    assert cli.normalize_argv(["work"]) == ["open", "work"]
    assert cli.normalize_argv(["."]) == ["open", "."]
    assert cli.normalize_argv(["ls", "--json"]) == ["ls", "--json"]
    assert cli.normalize_argv(["kill", "x"]) == ["kill", "x"]
    assert cli.normalize_argv(["--version"]) == ["--version"]


@pytest.fixture
def cli_env(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, list[str]]]:
    execs: list[tuple[str, list[str]]] = []
    monkeypatch.delenv("TM_SOCKET", raising=False)
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/tmux")
    monkeypatch.setattr(cli, "load_config", lambda: Config(default_dir="/tmp"))
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


def test_main_selects_the_pane_before_attaching(
    cli_env: list[tuple[str, list[str]]], fake_tmux: FakeTmux, monkeypatch: pytest.MonkeyPatch
) -> None:
    action = PostAction(kind="attach", target="beta", pane="%5")
    monkeypatch.setattr(cli, "run_tui", lambda config: action)
    cli.main([])
    assert fake_tmux.calls == [("select-pane", "%5")]
    assert cli_env == [("tmux", ["tmux", "attach-session", "-t", "=beta"])]


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


# ------------------------------------------------------------ subcommands


def test_open_existing_name_attaches(
    cli_env: list[tuple[str, list[str]]], fake_tmux: FakeTmux
) -> None:
    cli.main(["alpha"])
    assert fake_tmux.calls == []
    assert cli_env == [("tmux", ["tmux", "attach-session", "-t", "=alpha"])]


def test_open_new_name_creates_in_default_dir(
    cli_env: list[tuple[str, list[str]]], fake_tmux: FakeTmux
) -> None:
    cli.main(["my.new"])
    assert fake_tmux.calls == [("new", "my_new", "/tmp")]
    assert cli_env == [("tmux", ["tmux", "attach-session", "-t", "=my_new"])]


def test_open_directory_creates_session_there(
    cli_env: list[tuple[str, list[str]]], fake_tmux: FakeTmux, tmp_path: Path
) -> None:
    project = tmp_path / "proj.x"
    project.mkdir()
    cli.main([str(project)])
    assert fake_tmux.calls == [("new", "proj_x", str(project.resolve()))]
    assert cli_env == [("tmux", ["tmux", "attach-session", "-t", "=proj_x"])]


def test_open_dot_uses_cwd(
    cli_env: list[tuple[str, list[str]]],
    fake_tmux: FakeTmux,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "here"
    project.mkdir()
    monkeypatch.chdir(project)
    cli.main(["."])
    assert fake_tmux.calls == [("new", "here", str(project.resolve()))]


def test_open_switches_inside_tmux(
    cli_env: list[tuple[str, list[str]]], fake_tmux: FakeTmux, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_tmux.inside = True
    switched: list[str] = []
    monkeypatch.setattr(cli.tmux, "switch_client", switched.append)
    cli.main(["beta"])
    assert switched == ["beta"]
    assert cli_env == []


def test_open_missing_directory_fails(
    cli_env: list[tuple[str, list[str]]], fake_tmux: FakeTmux, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["/nonexistent/dir"])
    assert exc.value.code == 1
    assert "not a directory" in capsys.readouterr().err
    assert fake_tmux.calls == []


def test_ls_prints_sessions(
    cli_env: list[tuple[str, list[str]]], fake_tmux: FakeTmux, capsys: pytest.CaptureFixture[str]
) -> None:
    cli.main(["ls"])
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert lines[0].split()[:3] == ["alpha", "1", "0"]
    assert lines[1].split()[:3] == ["beta", "2", "1"]
    assert lines[1].endswith("/tmp/beta")


def test_ls_json(
    cli_env: list[tuple[str, list[str]]], fake_tmux: FakeTmux, capsys: pytest.CaptureFixture[str]
) -> None:
    cli.main(["ls", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert [s["name"] for s in data] == ["alpha", "beta"]
    assert data[1]["command"] == "vim"
    assert data[1]["attached"] == 1


def test_kill_session(cli_env: list[tuple[str, list[str]]], fake_tmux: FakeTmux) -> None:
    cli.main(["kill", "beta"])
    assert fake_tmux.calls == [("kill", "beta")]


def test_kill_reports_tmux_error(
    cli_env: list[tuple[str, list[str]]],
    fake_tmux: FakeTmux,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def boom(name: str) -> None:
        raise cli.tmux.TmuxError("can't find session: gone")

    monkeypatch.setattr(cli.tmux, "kill_session", boom)
    with pytest.raises(SystemExit) as exc:
        cli.main(["kill", "gone"])
    assert exc.value.code == 1
    assert "can't find session" in capsys.readouterr().err


# ----------------------------------------------------------------- agents


@pytest.fixture
def with_agents(fake_tmux: FakeTmux, monkeypatch: pytest.MonkeyPatch) -> FakeTmux:
    """beta runs a blocked claude (window 2) and an idle codex; sampling does not sleep."""
    monkeypatch.setattr(cli.agents.time, "sleep", lambda seconds: None)
    fake_tmux.add_agent(make_pane("beta", "%2", 200, path="/tmp/beta"), "codex")
    fake_tmux.add_agent(
        make_pane("beta", "%5", 500, window=2, pane=1, window_panes=2), "claude", CLAUDE_TRUST
    )
    return fake_tmux


def test_status_line(
    cli_env: list[tuple[str, list[str]]], with_agents: FakeTmux, capsys: pytest.CaptureFixture[str]
) -> None:
    cli.main(["status"])
    assert capsys.readouterr().out == "🔴1 ⚪1\n"
    cli.main(["status", "--ascii"])
    assert capsys.readouterr().out == "B1 I1\n"


def test_status_is_empty_without_agents(
    cli_env: list[tuple[str, list[str]]], fake_tmux: FakeTmux, capsys: pytest.CaptureFixture[str]
) -> None:
    cli.main(["status"])
    assert capsys.readouterr().out == ""


def test_agents_json(
    cli_env: list[tuple[str, list[str]]], with_agents: FakeTmux, capsys: pytest.CaptureFixture[str]
) -> None:
    cli.main(["agents", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert [(a["agent"], a["state"]) for a in data] == [("claude", "blocked"), ("codex", "idle")]
    assert set(data[0]) == {
        "session",
        "window",
        "window_name",
        "pane",
        "pane_id",
        "agent",
        "state",
        "path",
        "title",
        "seconds_since_change",
    }
    assert (data[0]["session"], data[0]["window"], data[0]["pane"]) == ("beta", 2, 1)
    assert data[0]["pane_id"] == "%5"
    assert isinstance(data[0]["seconds_since_change"], int)


def test_agents_text(
    cli_env: list[tuple[str, list[str]]], with_agents: FakeTmux, capsys: pytest.CaptureFixture[str]
) -> None:
    cli.main(["agents"])
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].split()[:5] == ["🔴", "blocked", "claude", "beta:2.1", "%5"]
    assert lines[1].split()[:5] == ["⚪", "idle", "codex", "beta:0.0", "%2"]
    assert lines[1].endswith("/tmp/beta")


def test_ls_json_includes_agents_per_session(
    cli_env: list[tuple[str, list[str]]], with_agents: FakeTmux, capsys: pytest.CaptureFixture[str]
) -> None:
    cli.main(["ls", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert data[0]["name"] == "alpha"
    assert data[0]["agents"] == []
    assert [a["pane_id"] for a in data[1]["agents"]] == ["%5", "%2"]
    assert data[1]["command"] == "vim"  # the existing fields stay


def test_agents_and_status_are_commands() -> None:
    assert cli.normalize_argv(["agents", "--json"]) == ["agents", "--json"]
    assert cli.normalize_argv(["status"]) == ["status"]
