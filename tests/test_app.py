import pytest
from textual.widgets import DataTable

from tmux_manager import tmux
from tmux_manager.app import TmuxManagerApp
from tmux_manager.config import Config
from tmux_manager.models import PostAction, TmuxSession


def make_sessions():
    return [
        TmuxSession(name="alpha", windows=1, attached=0, activity=1750000000, path="/tmp", created=1),
        TmuxSession(name="beta", windows=2, attached=1, activity=1750000000, path="/tmp", created=2),
    ]


@pytest.fixture
def fake_tmux(monkeypatch):
    monkeypatch.setattr(tmux, "list_sessions", lambda: make_sessions())
    monkeypatch.setattr(tmux, "capture_pane", lambda name: f"content of {name}")
    monkeypatch.setattr(tmux, "inside_tmux", lambda: False)
    monkeypatch.setattr(tmux, "current_session", lambda: None)


async def test_lists_sessions(fake_tmux):
    app = TmuxManagerApp(config=Config())
    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.screen.query_one(DataTable)
        assert table.row_count == 2


async def test_enter_attaches_selected(fake_tmux):
    app = TmuxManagerApp(config=Config())
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("j", "enter")
    assert app.return_value == PostAction(kind="attach", target="beta")


async def test_enter_switches_inside_tmux(fake_tmux, monkeypatch):
    monkeypatch.setattr(tmux, "inside_tmux", lambda: True)
    app = TmuxManagerApp(config=Config())
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
    assert app.return_value == PostAction(kind="switch", target="alpha")


async def test_q_quits_with_none(fake_tmux):
    app = TmuxManagerApp(config=Config())
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("q")
    assert app.return_value is None


async def test_empty_state_shown_without_sessions(monkeypatch):
    monkeypatch.setattr(tmux, "list_sessions", lambda: [])
    monkeypatch.setattr(tmux, "capture_pane", lambda name: "")
    app = TmuxManagerApp(config=Config())
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.screen.query_one("#empty").display
        assert not app.screen.query_one("#main").display


async def test_filter_narrows_table(fake_tmux):
    app = TmuxManagerApp(config=Config())
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("/", "b", "e")
        table = app.screen.query_one(DataTable)
        assert table.row_count == 1
        await pilot.press("escape")
        assert table.row_count == 2
