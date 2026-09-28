from dataclasses import replace

import pytest

from tmux_manager import agents, tmux
from tmux_manager.agents import Process
from tmux_manager.models import TmuxPane, TmuxSession


def make_sessions() -> list[TmuxSession]:
    return [
        TmuxSession(
            name="alpha",
            windows=1,
            attached=0,
            activity=1750000000,
            path="/tmp",
            current_path="/tmp",
            command="zsh",
        ),
        TmuxSession(
            name="beta",
            windows=2,
            attached=1,
            activity=1750000100,
            path="/tmp",
            current_path="/tmp/beta",
            command="vim",
        ),
    ]


def make_pane(
    session: str,
    pane_id: str,
    pid: int,
    *,
    window: int = 0,
    pane: int = 0,
    window_panes: int = 1,
    path: str = "/tmp",
) -> TmuxPane:
    return TmuxPane(
        session=session,
        window_index=window,
        window_name=f"win{window}",
        pane_index=pane,
        pane_id=pane_id,
        pane_pid=pid,
        command="zsh",
        current_path=path,
        window_activity=0,
        window_panes=window_panes,
        title="",
    )


CLAUDE_TRUST = (
    "─" * 40 + "\n ❯ 1. Yes, I trust this folder\n   2. No, exit\n\n"
    " Enter to confirm · Esc to cancel\n"
)


class FakeTmux:
    """Records mutations so tests can assert on what the UI asked tmux to do."""

    def __init__(self) -> None:
        self.sessions = make_sessions()
        self.calls: list[tuple[str, ...]] = []
        self.inside = False
        self.current: str | None = None
        self.popup_key: str | None = None
        # Panes and processes stay empty unless a test adds agents.
        self.panes: list[TmuxPane] = []
        self.processes: list[Process] = []
        self.screens: dict[str, str] = {}

    def add_agent(self, pane: TmuxPane, agent: str, screen: str = "") -> None:
        """Put a pane running ``agent`` (under a shell) into the fake server."""
        self.panes.append(pane)
        self.processes += [
            Process(pane.pane_pid, 1, "-zsh", "-zsh"),
            Process(pane.pane_pid + 1, pane.pane_pid, agent, f"{agent} --flag"),
        ]
        self.screens[pane.pane_id] = screen

    def list_panes(self) -> list[TmuxPane]:
        return list(self.panes)

    def capture_pane_by_id(self, pane_id: str, *, colors: bool = False) -> str:
        return self.screens.get(pane_id, "")

    def select_pane(self, pane_id: str) -> None:
        self.calls.append(("select-pane", pane_id))

    def list_sessions(self) -> list[TmuxSession]:
        return list(self.sessions)

    def capture_pane(self, name: str) -> str:
        return f"content of {name}"

    def has_session(self, name: str) -> bool:
        return any(s.name == name for s in self.sessions)

    def new_session(self, name: str, start_dir: str | None = None) -> None:
        self.calls.append(("new", name, start_dir or ""))

    def kill_session(self, name: str) -> None:
        self.calls.append(("kill", name))
        self.sessions = [s for s in self.sessions if s.name != name]

    def rename_session(self, old: str, new: str) -> None:
        self.calls.append(("rename", old, new))
        self.sessions = [replace(s, name=new) if s.name == old else s for s in self.sessions]

    def detach_clients(self, name: str) -> None:
        self.calls.append(("detach", name))


@pytest.fixture
def fake_tmux(monkeypatch: pytest.MonkeyPatch) -> FakeTmux:
    fake = FakeTmux()
    monkeypatch.setattr(tmux, "list_sessions", fake.list_sessions)
    monkeypatch.setattr(tmux, "capture_pane", fake.capture_pane)
    monkeypatch.setattr(tmux, "has_session", fake.has_session)
    monkeypatch.setattr(tmux, "new_session", fake.new_session)
    monkeypatch.setattr(tmux, "kill_session", fake.kill_session)
    monkeypatch.setattr(tmux, "rename_session", fake.rename_session)
    monkeypatch.setattr(tmux, "detach_clients", fake.detach_clients)
    monkeypatch.setattr(tmux, "inside_tmux", lambda: fake.inside)
    monkeypatch.setattr(tmux, "current_session", lambda: fake.current)
    monkeypatch.setattr(tmux, "popup_binding", lambda: fake.popup_key)
    monkeypatch.setattr(tmux, "list_panes", fake.list_panes)
    monkeypatch.setattr(tmux, "capture_pane_by_id", fake.capture_pane_by_id)
    monkeypatch.setattr(tmux, "select_pane", fake.select_pane)
    monkeypatch.setattr(agents, "read_processes", lambda: list(fake.processes))
    return fake
