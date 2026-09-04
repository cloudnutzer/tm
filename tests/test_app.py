from textual.pilot import Pilot
from textual.widgets import DataTable, Static

from tmux_manager.app import TmuxManagerApp
from tmux_manager.config import Config
from tmux_manager.models import PostAction

from .conftest import FakeTmux


async def settle(pilot: Pilot[PostAction]) -> None:
    """Let debounce timers fire and background tmux workers finish."""
    await pilot.pause(0.15)
    await pilot.app.workers.wait_for_complete()
    await pilot.pause()


async def test_lists_sessions(fake_tmux: FakeTmux) -> None:
    app = TmuxManagerApp(config=Config())
    async with app.run_test() as pilot:
        await settle(pilot)
        table = app.screen.query_one(DataTable)
        assert table.row_count == 2
        assert str(table.get_cell_at((1, 2))) == "1"  # beta has one attached client


async def test_preview_shows_highlighted_session(fake_tmux: FakeTmux) -> None:
    app = TmuxManagerApp(config=Config())
    async with app.run_test() as pilot:
        await settle(pilot)
        assert "content of alpha" in str(app.screen.query_one("#preview", Static).visual)
        await pilot.press("j")
        await settle(pilot)
        assert "content of beta" in str(app.screen.query_one("#preview", Static).visual)


async def test_enter_attaches_selected(fake_tmux: FakeTmux) -> None:
    app = TmuxManagerApp(config=Config())
    async with app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("j", "enter")
    assert app.return_value == PostAction(kind="attach", target="beta")


async def test_enter_switches_inside_tmux(fake_tmux: FakeTmux) -> None:
    fake_tmux.inside = True
    app = TmuxManagerApp(config=Config())
    async with app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("enter")
    assert app.return_value == PostAction(kind="switch", target="alpha")


async def test_q_quits_with_none(fake_tmux: FakeTmux) -> None:
    app = TmuxManagerApp(config=Config())
    async with app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("q")
    assert app.return_value is None


async def test_empty_state_shown_without_sessions(fake_tmux: FakeTmux) -> None:
    fake_tmux.sessions = []
    app = TmuxManagerApp(config=Config())
    async with app.run_test() as pilot:
        await settle(pilot)
        assert app.screen.query_one("#empty").display
        assert not app.screen.query_one("#main").display


async def test_filter_narrows_table(fake_tmux: FakeTmux) -> None:
    app = TmuxManagerApp(config=Config())
    async with app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("/", "b", "e")
        table = app.screen.query_one(DataTable)
        assert table.row_count == 1
        await pilot.press("escape")
        assert table.row_count == 2


async def test_unchanged_sessions_do_not_rebuild_table(fake_tmux: FakeTmux) -> None:
    app = TmuxManagerApp(config=Config())
    async with app.run_test() as pilot:
        await settle(pilot)
        table = app.screen.query_one(DataTable)
        rebuilds: list[int] = []
        original_clear = table.clear

        def counting_clear(columns: bool = False) -> DataTable:
            rebuilds.append(1)
            return original_clear(columns)

        table.clear = counting_clear  # type: ignore[method-assign]
        app.screen.refresh_sessions()  # type: ignore[attr-defined]
        await settle(pilot)
        assert rebuilds == []
        fake_tmux.sessions = fake_tmux.sessions[:1]
        app.screen.refresh_sessions()  # type: ignore[attr-defined]
        await settle(pilot)
        assert rebuilds == [1]
        assert table.row_count == 1


async def test_kill_asks_for_confirmation(fake_tmux: FakeTmux) -> None:
    app = TmuxManagerApp(config=Config())
    async with app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("d")
        await pilot.pause()
        await pilot.press("n")  # decline
        await settle(pilot)
        assert fake_tmux.calls == []
        await pilot.press("d")
        await pilot.pause()
        await pilot.press("y")
        await settle(pilot)
        assert fake_tmux.calls == [("kill", "alpha")]
        assert app.screen.query_one(DataTable).row_count == 1


async def test_new_session_creates_and_attaches(fake_tmux: FakeTmux) -> None:
    app = TmuxManagerApp(config=Config(default_dir="/tmp"))
    async with app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("n")
        await pilot.pause()
        await pilot.press("g", "a", "m", "m", "a", "enter")
        await settle(pilot)
    assert fake_tmux.calls == [("new", "gamma", "/tmp")]
    assert app.return_value == PostAction(kind="attach", target="gamma")


async def test_rename_session(fake_tmux: FakeTmux) -> None:
    app = TmuxManagerApp(config=Config())
    async with app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("r")
        await pilot.pause()
        await pilot.press("end", "2", "enter")
        await settle(pilot)
        assert fake_tmux.calls == [("rename", "alpha", "alpha2")]


async def test_detach_clients(fake_tmux: FakeTmux) -> None:
    app = TmuxManagerApp(config=Config())
    async with app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("j", "D")
        await pilot.pause()
        await pilot.press("y")
        await settle(pilot)
        assert fake_tmux.calls == [("detach", "beta")]
