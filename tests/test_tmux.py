import subprocess
from collections.abc import Callable

import pytest

from tmux_manager import tmux
from tmux_manager.models import PostAction, TmuxPane

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


def test_list_panes_parses_fields_with_utf8_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    claude = line(
        "work", "1", "editor", "0", "%3", "4242", "2.1.281", "/tmp/x", "1750000000", "2",
        "✳ Claude Code",
    )  # fmt: skip
    shell = line("my session", "2", "zsh", "1", "%7", "99", "zsh", "/tmp", "1750000100", "1", "")
    fake, calls = fake_run(stdout=claude + "\n" + shell + "\n")
    monkeypatch.setattr(tmux, "_run", fake)
    panes = tmux.list_panes()
    assert calls == [["-u", "list-panes", "-a", "-F", tmux.PANE_FORMAT]]
    assert [p.pane_id for p in panes] == ["%3", "%7"]
    first = panes[0]
    assert (first.session, first.window_index, first.window_name, first.pane_index) == (
        "work",
        1,
        "editor",
        0,
    )
    assert first.pane_pid == 4242
    assert first.command == "2.1.281"
    assert first.current_path == "/tmp/x"
    assert first.window_activity == 1750000000
    assert first.window_panes == 2
    assert first.title == "✳ Claude Code"
    assert first.agent is None
    assert panes[1].session == "my session"
    assert panes[1].title == ""


def test_list_panes_keeps_separator_inside_title(monkeypatch: pytest.MonkeyPatch) -> None:
    odd = line("s", "0", "w", "0", "%1", "1", "zsh", "/", "0", "1", "a\x1fb")
    fake, _ = fake_run(stdout=odd + "\n")
    monkeypatch.setattr(tmux, "_run", fake)
    assert tmux.list_panes()[0].title == "a\x1fb"


def test_list_panes_no_server_is_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    fake, _ = fake_run(stderr="no server running on /tmp/tmux-501/default", returncode=1)
    monkeypatch.setattr(tmux, "_run", fake)
    assert tmux.list_panes() == []


def test_capture_pane_by_id_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    fake, calls = fake_run(stdout="text")
    monkeypatch.setattr(tmux, "_run", fake)
    assert tmux.capture_pane_by_id("%5") == "text"
    tmux.capture_pane_by_id("%5", colors=True)
    assert calls == [
        ["-u", "capture-pane", "-p", "-t", "%5"],
        ["-u", "capture-pane", "-ep", "-t", "%5"],
    ]


def test_select_pane_selects_window_then_pane(monkeypatch: pytest.MonkeyPatch) -> None:
    fake, calls = fake_run()
    monkeypatch.setattr(tmux, "_run", fake)
    tmux.select_pane("%5")
    assert calls == [["select-window", "-t", "%5"], ["select-pane", "-t", "%5"]]


def test_pane_action_carries_the_pane(monkeypatch: pytest.MonkeyPatch) -> None:
    pane = TmuxPane("work", 2, "api", 1, "%5", 42, "zsh", "/tmp", 0, 2, "", "claude")
    monkeypatch.delenv("TMUX", raising=False)
    assert tmux.pane_action(pane) == PostAction(kind="attach", target="work", pane="%5")
    monkeypatch.setenv("TMUX", "/tmp/tmux-1/default,123,0")
    assert tmux.pane_action(pane) == PostAction(kind="switch", target="work", pane="%5")
