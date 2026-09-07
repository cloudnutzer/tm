"""Stage-2 UX behaviour: preview tail, markers, sort, preview toggle, help, validation."""

import pytest
from rich.text import Text
from textual.pilot import Pilot
from textual.widgets import DataTable, Static

from tmux_manager import tmux
from tmux_manager.app import TmuxManagerApp
from tmux_manager.config import Config
from tmux_manager.models import PostAction
from tmux_manager.screens.modals import HelpModal
from tmux_manager.screens.sessions import tail_of_pane

from .conftest import FakeTmux


async def settle(pilot: Pilot[PostAction]) -> None:
    await pilot.pause(0.15)
    await pilot.app.workers.wait_for_complete()
    await pilot.pause()


def preview(app: TmuxManagerApp) -> Static:
    return app.screen.query_one("#preview", Static)


def test_tail_of_pane_keeps_last_lines_and_drops_blank_tail() -> None:
    content = "\n".join(str(i) for i in range(1, 51)) + "\n$ \n\n\n\n"
    text = tail_of_pane(content, 5)
    assert text.plain.splitlines() == ["47", "48", "49", "50", "$"]


def test_tail_of_pane_keeps_colors() -> None:
    text = tail_of_pane("\x1b[31mred\x1b[0m   \n\n", 10)
    assert text.plain == "red"
    assert text.spans and text.spans[0].style.color is not None  # type: ignore[union-attr]


def test_tail_of_pane_without_height_keeps_everything() -> None:
    assert tail_of_pane("a\nb\nc\n", 0).plain == "a\nb\nc"


async def test_preview_shows_pane_tail_with_title(
    fake_tmux: FakeTmux, monkeypatch: pytest.MonkeyPatch
) -> None:
    tall = "\n".join(str(i) for i in range(200)) + "\n\n\n"
    monkeypatch.setattr(tmux, "capture_pane", lambda name: tall)
    app = TmuxManagerApp(config=Config())
    async with app.run_test(size=(120, 24)) as pilot:
        await settle(pilot)
        shown = str(preview(app).visual).splitlines()
        assert shown[-1] == "199"
        assert len(shown) == preview(app).content_size.height
        assert preview(app).border_title == "alpha  zsh"


async def test_current_session_is_marked_inside_tmux(fake_tmux: FakeTmux) -> None:
    fake_tmux.inside = True
    fake_tmux.current = "beta"
    app = TmuxManagerApp(config=Config())
    async with app.run_test() as pilot:
        await settle(pilot)
        table = app.screen.query_one(DataTable)
        assert str(table.get_cell_at((0, 0))) == "  alpha"
        assert str(table.get_cell_at((1, 0))) == "▸ beta"
        assert app.screen.sub_title == "2 sessions · by name · inside tmux"


async def test_outside_tmux_has_no_marker_column(fake_tmux: FakeTmux) -> None:
    app = TmuxManagerApp(config=Config())
    async with app.run_test() as pilot:
        await settle(pilot)
        table = app.screen.query_one(DataTable)
        assert str(table.get_cell_at((0, 0))) == "alpha"
        assert app.screen.sub_title == "2 sessions · by name · outside tmux"


async def test_sort_toggle_orders_by_activity(fake_tmux: FakeTmux) -> None:
    app = TmuxManagerApp(config=Config())
    async with app.run_test() as pilot:
        await settle(pilot)
        table = app.screen.query_one(DataTable)
        await pilot.press("s")
        assert str(table.get_cell_at((0, 0))) == "beta"  # most recent activity first
        assert "by activity" in str(app.screen.sub_title)
        await pilot.press("s")
        assert str(table.get_cell_at((0, 0))) == "alpha"


async def test_sort_from_config(fake_tmux: FakeTmux) -> None:
    app = TmuxManagerApp(config=Config(sort="activity"))
    async with app.run_test() as pilot:
        await settle(pilot)
        assert str(app.screen.query_one(DataTable).get_cell_at((0, 0))) == "beta"


async def test_preview_toggle(fake_tmux: FakeTmux) -> None:
    app = TmuxManagerApp(config=Config())
    async with app.run_test(size=(120, 24)) as pilot:
        await settle(pilot)
        assert preview(app).display
        await pilot.press("v")
        assert not preview(app).display
        await pilot.press("v")
        assert preview(app).display


async def test_preview_hidden_on_narrow_terminal(
    fake_tmux: FakeTmux, monkeypatch: pytest.MonkeyPatch
) -> None:
    captures: list[str] = []

    def capture(name: str) -> str:
        captures.append(name)
        return "x"

    monkeypatch.setattr(tmux, "capture_pane", capture)
    app = TmuxManagerApp(config=Config())
    async with app.run_test(size=(70, 24)) as pilot:
        await settle(pilot)
        assert not preview(app).display
        assert captures == []  # no capture-pane calls while hidden


async def test_preview_disabled_by_config(fake_tmux: FakeTmux) -> None:
    app = TmuxManagerApp(config=Config(show_preview=False, preview_width=55))
    async with app.run_test(size=(120, 24)) as pilot:
        await settle(pilot)
        assert not preview(app).display
        assert preview(app).styles.width is not None
        assert preview(app).styles.width.value == 55


async def test_help_modal_opens_and_closes(fake_tmux: FakeTmux) -> None:
    app = TmuxManagerApp(config=Config())
    async with app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("question_mark")
        await pilot.pause()
        assert isinstance(app.screen, HelpModal)
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, HelpModal)


async def test_filter_without_match_explains(fake_tmux: FakeTmux) -> None:
    app = TmuxManagerApp(config=Config())
    async with app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("/", "z", "z")
        empty = app.screen.query_one("#empty", Static)
        assert empty.display
        assert "No sessions match 'zz'" in str(empty.visual)
        await pilot.press("escape")
        assert not empty.display


async def test_new_session_rejects_existing_name(fake_tmux: FakeTmux) -> None:
    app = TmuxManagerApp(config=Config(default_dir="/tmp"))
    async with app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("n")
        await pilot.pause()
        await pilot.press("b", "e", "t", "a", "enter")
        await pilot.pause()
        error = app.screen.query_one("#error", Static)
        assert "already exists" in str(error.visual)
        assert fake_tmux.calls == []
        await pilot.press("escape")
        await settle(pilot)
    assert app.return_value is None


async def test_rename_rejects_existing_name_but_allows_own(fake_tmux: FakeTmux) -> None:
    app = TmuxManagerApp(config=Config())
    async with app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("r")
        await pilot.pause()
        await pilot.press("ctrl+u", "b", "e", "t", "a", "enter")
        await pilot.pause()
        assert "already exists" in str(app.screen.query_one("#error", Static).visual)
        await pilot.press("ctrl+u", "a", "l", "p", "h", "a", "enter")
        await settle(pilot)
        assert fake_tmux.calls == []  # same name: nothing to do


def test_text_marker_rows_compare_equal() -> None:
    # _render_table relies on row equality to skip rebuilds
    assert Text("▸ x", style="bold") == Text("▸ x", style="bold")


def hint(app: TmuxManagerApp) -> str:
    return str(app.screen.query_one("#hint", Static).visual)


def test_switch_hint_variants() -> None:
    from tmux_manager.screens.sessions import switch_hint

    assert "prefix S opens" in switch_hint(inside=True, popup_key="S")
    assert "add to ~/.tmux.conf: bind S" in switch_hint(inside=True, popup_key=None)
    assert "prefix M-s opens" in switch_hint(inside=False, popup_key="M-s")
    assert "run tm again" in switch_hint(inside=False, popup_key=None)
    for inside in (True, False):
        for key in ("S", None):
            assert "no need to detach" in switch_hint(inside=inside, popup_key=key)


async def test_hint_names_popup_key_inside_tmux(fake_tmux: FakeTmux) -> None:
    fake_tmux.inside = True
    fake_tmux.current = "alpha"
    fake_tmux.popup_key = "S"
    app = TmuxManagerApp(config=Config())
    async with app.run_test() as pilot:
        await settle(pilot)
        assert app.screen.query_one("#hint").display
        assert "Enter switches" in hint(app)
        assert "prefix S opens this picker" in hint(app)


async def test_hint_suggests_binding_when_missing(fake_tmux: FakeTmux) -> None:
    app = TmuxManagerApp(config=Config())
    async with app.run_test() as pilot:
        await settle(pilot)
        assert "run tm again" in hint(app)
        assert "bind S display-popup" in hint(app)


async def test_hint_stays_visible_in_empty_state(fake_tmux: FakeTmux) -> None:
    fake_tmux.sessions = []
    app = TmuxManagerApp(config=Config())
    async with app.run_test() as pilot:
        await settle(pilot)
        assert app.screen.query_one("#empty").display
        assert app.screen.query_one("#hint").display
        assert "no need to detach" in hint(app)
