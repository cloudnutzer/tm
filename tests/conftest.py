import pytest

from tmux_manager import tmux
from tmux_manager.models import TmuxSession


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


class FakeTmux:
    """Records mutations so tests can assert on what the UI asked tmux to do."""

    def __init__(self) -> None:
        self.sessions = make_sessions()
        self.calls: list[tuple[str, ...]] = []
        self.inside = False
        self.current: str | None = None

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
    return fake
