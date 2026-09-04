from pathlib import Path

from textual.widgets import OptionList

from tmux_manager.app import TmuxManagerApp
from tmux_manager.config import Config
from tmux_manager.models import PostAction
from tmux_manager.screens.sessionizer import discover_projects

from .conftest import FakeTmux


def test_discover_projects_skips_hidden_and_files(tmp_path: Path) -> None:
    (tmp_path / "beta").mkdir()
    (tmp_path / "alpha").mkdir()
    (tmp_path / ".hidden").mkdir()
    (tmp_path / "file.txt").write_text("x")
    projects = discover_projects((tmp_path,))
    assert list(projects) == ["alpha", "beta"]
    assert projects["alpha"] == tmp_path / "alpha"


def test_discover_projects_sanitizes_and_keeps_first_duplicate(tmp_path: Path) -> None:
    root1 = tmp_path / "r1"
    root2 = tmp_path / "r2"
    (root1 / "my.app").mkdir(parents=True)
    (root2 / "my_app").mkdir(parents=True)
    projects = discover_projects((root1, root2))
    assert list(projects) == ["my_app"]
    assert projects["my_app"] == root1 / "my.app"


def test_discover_projects_ignores_missing_roots(tmp_path: Path) -> None:
    assert discover_projects((tmp_path / "nope",)) == {}


async def test_sessionizer_lists_projects_and_marks_existing(
    fake_tmux: FakeTmux, tmp_path: Path
) -> None:
    (tmp_path / "alpha").mkdir()
    (tmp_path / "gamma").mkdir()
    app = TmuxManagerApp(config=Config(project_roots=(tmp_path,)))
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("p")
        await pilot.pause()
        option_list = app.screen.query_one(OptionList)
        assert option_list.option_count == 2
        assert str(option_list.get_option_at_index(0).prompt).startswith("● alpha")
        assert str(option_list.get_option_at_index(1).prompt).startswith("  gamma")


async def test_sessionizer_creates_missing_session(fake_tmux: FakeTmux, tmp_path: Path) -> None:
    (tmp_path / "alpha").mkdir()
    (tmp_path / "gamma").mkdir()
    app = TmuxManagerApp(config=Config(project_roots=(tmp_path,)))
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("p")
        await pilot.pause()
        await pilot.press("j", "enter")
    assert fake_tmux.calls == [("new", "gamma", str(tmp_path / "gamma"))]
    assert app.return_value == PostAction(kind="attach", target="gamma")


async def test_sessionizer_reuses_existing_session(fake_tmux: FakeTmux, tmp_path: Path) -> None:
    (tmp_path / "alpha").mkdir()
    app = TmuxManagerApp(config=Config(project_roots=(tmp_path,)))
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("p")
        await pilot.pause()
        await pilot.press("enter")
    assert fake_tmux.calls == []
    assert app.return_value == PostAction(kind="attach", target="alpha")


async def test_sessionizer_escape_returns_to_list(fake_tmux: FakeTmux, tmp_path: Path) -> None:
    app = TmuxManagerApp(config=Config(project_roots=(tmp_path,)))
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("p")
        await pilot.pause()
        assert "No project directories found" in str(
            app.screen.query_one("#sessionizer-hint").visual
        )
        await pilot.press("escape")
        await pilot.pause()
        assert app.screen.query("#sessions")
