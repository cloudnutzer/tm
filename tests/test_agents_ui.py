"""Agent status in the TUI: the Agents column, the agents screen, jumping to a pane."""

import time
from dataclasses import replace

from textual.pilot import Pilot
from textual.widgets import DataTable, Static

from tmux_manager.app import TmuxManagerApp
from tmux_manager.config import Config
from tmux_manager.models import PostAction
from tmux_manager.screens.agents import AgentsScreen
from tmux_manager.screens.modals import HelpModal
from tmux_manager.screens.sessions import SessionsScreen

from .conftest import CLAUDE_TRUST, FakeTmux, make_pane


async def settle(pilot: Pilot[PostAction]) -> None:
    await pilot.pause(0.15)
    await pilot.app.workers.wait_for_complete()
    await pilot.pause()


def add_agents(fake: FakeTmux) -> None:
    """beta: an idle codex, a blocked claude in window 2, a working opencode."""
    fake.add_agent(make_pane("beta", "%2", 200, window=0, path="/tmp/beta"), "codex")
    fake.add_agent(
        make_pane("beta", "%5", 500, window=2, pane=1, window_panes=2, path="/tmp/api"),
        "claude",
        CLAUDE_TRUST,
    )
    busy = replace(make_pane("alpha", "%8", 800, window=1), window_activity=int(time.time()))
    fake.add_agent(busy, "opencode")


def column(table: DataTable[object], index: int) -> list[str]:
    return [str(table.get_cell_at((row, index))) for row in range(table.row_count)]


async def test_agents_column_rolls_up_per_session(fake_tmux: FakeTmux) -> None:
    add_agents(fake_tmux)
    app = TmuxManagerApp(config=Config())
    async with app.run_test(size=(140, 24)) as pilot:
        await settle(pilot)
        table = app.screen.query_one(DataTable)
        assert [str(c.label) for c in table.columns.values()][4] == "Agents"
        assert column(table, 4) == ["🟢1", "🔴1 ⚪1"]


async def test_agents_column_is_empty_without_agents(fake_tmux: FakeTmux) -> None:
    app = TmuxManagerApp(config=Config())
    async with app.run_test() as pilot:
        await settle(pilot)
        assert column(app.screen.query_one(DataTable), 4) == ["", ""]


async def test_agents_screen_lists_blocked_first(fake_tmux: FakeTmux) -> None:
    add_agents(fake_tmux)
    app = TmuxManagerApp(config=Config())
    async with app.run_test(size=(140, 24)) as pilot:
        await settle(pilot)
        await pilot.press("a")
        await settle(pilot)
        assert isinstance(app.screen, AgentsScreen)
        table = app.screen.query_one(DataTable)
        assert column(table, 0) == ["🔴 blocked", "🟢 working", "⚪ idle"]
        assert column(table, 1) == ["claude", "opencode", "codex"]
        assert column(table, 2) == ["beta", "alpha", "beta"]
        assert column(table, 3) == ["2.1:win2", "1:win1", "0:win0"]
        assert column(table, 4) == ["/tmp/api", "/tmp", "/tmp/beta"]
        assert app.screen.sub_title == "3 agents · 🔴1 🟢1 ⚪1"
        preview = app.screen.query_one("#preview", Static)
        assert "Enter to confirm" in str(preview.visual)
        assert preview.border_title == "beta:2.1  claude"


async def test_enter_jumps_to_the_agent_pane(fake_tmux: FakeTmux) -> None:
    add_agents(fake_tmux)
    app = TmuxManagerApp(config=Config())
    async with app.run_test(size=(140, 24)) as pilot:
        await settle(pilot)
        await pilot.press("a")
        await settle(pilot)
        await pilot.press("enter")
    # the blocked claude sits in beta's window 2, not the window beta shows
    assert app.return_value == PostAction(kind="attach", target="beta", pane="%5")


async def test_enter_switches_to_the_pane_inside_tmux(fake_tmux: FakeTmux) -> None:
    add_agents(fake_tmux)
    fake_tmux.inside = True
    app = TmuxManagerApp(config=Config())
    async with app.run_test(size=(140, 24)) as pilot:
        await settle(pilot)
        await pilot.press("a")
        await settle(pilot)
        await pilot.press("j", "j", "enter")
    assert app.return_value == PostAction(kind="switch", target="beta", pane="%2")


async def test_agents_filter_and_escape(fake_tmux: FakeTmux) -> None:
    add_agents(fake_tmux)
    app = TmuxManagerApp(config=Config())
    async with app.run_test(size=(140, 24)) as pilot:
        await settle(pilot)
        await pilot.press("a")
        await settle(pilot)
        await pilot.press("/", *"alpha")
        await settle(pilot)
        table = app.screen.query_one(DataTable)
        assert column(table, 1) == ["opencode"]
        await pilot.press("escape")  # clears the filter
        await settle(pilot)
        assert table.row_count == 3
        await pilot.press("escape")  # back to the session list
        await settle(pilot)
        assert isinstance(app.screen, SessionsScreen)


async def test_agents_screen_empty_state_and_help(fake_tmux: FakeTmux) -> None:
    app = TmuxManagerApp(config=Config())
    async with app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("a")
        await settle(pilot)
        assert "No coding agents" in str(app.screen.query_one("#empty", Static).visual)
        await pilot.press("question_mark")
        await settle(pilot)
        assert isinstance(app.screen, HelpModal)
