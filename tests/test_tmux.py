import subprocess
from collections.abc import Callable

import pytest

from tmux_manager import tmux
from tmux_manager.models import PostAction

FakeRun = Callable[[list[str]], subprocess.CompletedProcess[str]]


def fake_run(
    stdout: str = "", stderr: str = "", returncode: int = 0
) -> tuple[FakeRun, list[list[str]]]:
    calls: list[list[str]] = []

    def _fake(args: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args, returncode, stdout, stderr)

    return _fake, calls


def line(*fields: str) -> str:
    return "\x1f".join(fields)


def test_list_sessions_parses_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    line1 = line("work", "3", "1", "1750000000", "/Users/x/git projects/work", "/Users/x", "vim")
    line2 = line("my session", "1", "0", "1750000100", "/tmp", "/tmp/sub", "zsh")
    fake, _ = fake_run(stdout=line1 + "\n" + line2 + "\n")
    monkeypatch.setattr(tmux, "_run", fake)
    sessions = tmux.list_sessions()
    assert [s.name for s in sessions] == ["work", "my session"]
    assert sessions[0].windows == 3
    assert sessions[0].attached == 1
    assert sessions[0].path == "/Users/x/git projects/work"
    assert sessions[0].current_path == "/Users/x"
    assert sessions[0].command == "vim"
    assert sessions[1].activity == 1750000100


def test_list_sessions_no_server_is_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    fake, _ = fake_run(stderr="no server running on /private/tmp/tmux-501/default", returncode=1)
    monkeypatch.setattr(tmux, "_run", fake)
    assert tmux.list_sessions() == []


def test_list_sessions_other_error_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    fake, _ = fake_run(stderr="some other failure", returncode=1)
    monkeypatch.setattr(tmux, "_run", fake)
    with pytest.raises(tmux.TmuxError):
        tmux.list_sessions()


def test_missing_tmux_binary_is_a_tmux_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("tmux")

    monkeypatch.setattr(tmux.subprocess, "run", missing)
    with pytest.raises(tmux.TmuxError, match="not found"):
        tmux.list_sessions()


def test_sanitize_session_name() -> None:
    assert tmux.sanitize_session_name("my.proj:x") == "my_proj_x"
    assert tmux.sanitize_session_name("  ok  ") == "ok"
    assert tmux.sanitize_session_name("-flag") == "_flag"
    with pytest.raises(ValueError):
        tmux.sanitize_session_name("   ")


def test_attach_action_depends_on_tmux_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TMUX", raising=False)
    assert tmux.attach_action("work") == PostAction(kind="attach", target="work")
    monkeypatch.setenv("TMUX", "/tmp/tmux-1/default,123,0")
    assert tmux.attach_action("work") == PostAction(kind="switch", target="work")


def test_new_session_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    fake, calls = fake_run()
    monkeypatch.setattr(tmux, "_run", fake)
    tmux.new_session("a b", "/tmp")
    assert calls == [["new-session", "-d", "-s", "a b", "-c", "/tmp"]]


def test_new_session_without_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    fake, calls = fake_run()
    monkeypatch.setattr(tmux, "_run", fake)
    tmux.new_session("plain")
    assert calls == [["new-session", "-d", "-s", "plain"]]


def test_kill_session_uses_exact_target(monkeypatch: pytest.MonkeyPatch) -> None:
    fake, calls = fake_run()
    monkeypatch.setattr(tmux, "_run", fake)
    tmux.kill_session("work")
    assert calls == [["kill-session", "-t", "=work"]]


def test_capture_pane_uses_session_qualified_target(monkeypatch: pytest.MonkeyPatch) -> None:
    fake, calls = fake_run(stdout="pane content")
    monkeypatch.setattr(tmux, "_run", fake)
    assert tmux.capture_pane("work") == "pane content"
    assert calls == [["capture-pane", "-ep", "-t", "=work:"]]


def test_rename_session_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    fake, calls = fake_run()
    monkeypatch.setattr(tmux, "_run", fake)
    tmux.rename_session("old", "new")
    assert calls == [["rename-session", "-t", "=old", "new"]]


def test_failed_mutation_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    fake, _ = fake_run(stderr="can't find session", returncode=1)
    monkeypatch.setattr(tmux, "_run", fake)
    with pytest.raises(tmux.TmuxError, match="can't find session"):
        tmux.kill_session("gone")


def test_tm_socket_routes_to_isolated_server(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TM_SOCKET", "tmtest")
    assert tmux.base_argv() == ["tmux", "-L", "tmtest"]
    monkeypatch.delenv("TM_SOCKET")
    assert tmux.base_argv() == ["tmux"]


LIST_KEYS = """\
bind-key    -T prefix       C-z                  suspend-client
bind-key    -T prefix       S                    display-popup -E -w 80% -h 75% tm
bind-key    -T prefix       T                    display-popup -E tmux-other-tool
"""


def test_popup_binding_finds_key(monkeypatch: pytest.MonkeyPatch) -> None:
    fake, calls = fake_run(stdout=LIST_KEYS)
    monkeypatch.setattr(tmux, "_run", fake)
    assert tmux.popup_binding() == "S"
    assert calls == [["list-keys", "-T", "prefix"]]


def test_popup_binding_ignores_other_popups_and_missing_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake, _ = fake_run(stdout=LIST_KEYS.splitlines()[2] + "\n")
    monkeypatch.setattr(tmux, "_run", fake)
    assert tmux.popup_binding() is None
    fake, _ = fake_run(stderr="no server running on /tmp/tmux-501/default", returncode=1)
    monkeypatch.setattr(tmux, "_run", fake)
    assert tmux.popup_binding() is None


def test_popup_binding_with_note_and_full_path(monkeypatch: pytest.MonkeyPatch) -> None:
    line = 'bind-key -N "Session picker" -T prefix M-s display-popup -E /usr/local/bin/tm\n'
    fake, _ = fake_run(stdout=line)
    monkeypatch.setattr(tmux, "_run", fake)
    assert tmux.popup_binding() == "M-s"
