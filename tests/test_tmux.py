import subprocess

import pytest

from tmux_manager import tmux


def fake_run(stdout="", stderr="", returncode=0):
    calls = []

    def _fake(args):
        calls.append(args)
        return subprocess.CompletedProcess(args, returncode, stdout, stderr)

    return _fake, calls


def test_list_sessions_parses_fields(monkeypatch):
    line1 = "\x1f".join(["work", "3", "1", "1750000000", "/Users/x/git projects/work", "1749000000"])
    line2 = "\x1f".join(["my session", "1", "0", "1750000100", "/tmp", "1749000100"])
    fake, _ = fake_run(stdout=line1 + "\n" + line2 + "\n")
    monkeypatch.setattr(tmux, "_run", fake)
    sessions = tmux.list_sessions()
    assert [s.name for s in sessions] == ["work", "my session"]
    assert sessions[0].windows == 3
    assert sessions[0].attached == 1
    assert sessions[0].path == "/Users/x/git projects/work"
    assert sessions[1].activity == 1750000100


def test_list_sessions_no_server_is_empty(monkeypatch):
    fake, _ = fake_run(stderr="no server running on /private/tmp/tmux-501/default", returncode=1)
    monkeypatch.setattr(tmux, "_run", fake)
    assert tmux.list_sessions() == []


def test_list_sessions_other_error_raises(monkeypatch):
    fake, _ = fake_run(stderr="some other failure", returncode=1)
    monkeypatch.setattr(tmux, "_run", fake)
    with pytest.raises(tmux.TmuxError):
        tmux.list_sessions()


def test_sanitize_session_name():
    assert tmux.sanitize_session_name("my.proj:x") == "my_proj_x"
    assert tmux.sanitize_session_name("  ok  ") == "ok"
    with pytest.raises(ValueError):
        tmux.sanitize_session_name("   ")


def test_new_session_argv(monkeypatch):
    fake, calls = fake_run()
    monkeypatch.setattr(tmux, "_run", fake)
    tmux.new_session("a b", "/tmp")
    assert calls == [["new-session", "-d", "-s", "a b", "-c", "/tmp"]]


def test_new_session_without_dir(monkeypatch):
    fake, calls = fake_run()
    monkeypatch.setattr(tmux, "_run", fake)
    tmux.new_session("plain")
    assert calls == [["new-session", "-d", "-s", "plain"]]


def test_kill_session_uses_exact_target(monkeypatch):
    fake, calls = fake_run()
    monkeypatch.setattr(tmux, "_run", fake)
    tmux.kill_session("work")
    assert calls == [["kill-session", "-t", "=work"]]


def test_capture_pane_uses_session_qualified_target(monkeypatch):
    fake, calls = fake_run(stdout="pane content")
    monkeypatch.setattr(tmux, "_run", fake)
    assert tmux.capture_pane("work") == "pane content"
    assert calls == [["capture-pane", "-ep", "-t", "=work:"]]


def test_rename_session_argv(monkeypatch):
    fake, calls = fake_run()
    monkeypatch.setattr(tmux, "_run", fake)
    tmux.rename_session("old", "new")
    assert calls == [["rename-session", "-t", "=old", "new"]]


def test_failed_mutation_raises(monkeypatch):
    fake, _ = fake_run(stderr="can't find session", returncode=1)
    monkeypatch.setattr(tmux, "_run", fake)
    with pytest.raises(tmux.TmuxError, match="can't find session"):
        tmux.kill_session("gone")


def test_tm_socket_routes_to_isolated_server(monkeypatch):
    monkeypatch.setenv("TM_SOCKET", "tmtest")
    assert tmux.base_argv() == ["tmux", "-L", "tmtest"]
    monkeypatch.delenv("TM_SOCKET")
    assert tmux.base_argv() == ["tmux"]
