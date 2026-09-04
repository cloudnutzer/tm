from pathlib import Path

from textual.widgets import Input, OptionList

from tmux_manager.app import TmuxManagerApp
from tmux_manager.config import Config
from tmux_manager.models import PostAction
from tmux_manager.screens.sessionizer import discover_projects, match_projects

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


def test_match_projects_fuzzy_orders_best_first() -> None:
    projects = {
        "tmux-manager": Path("/p/tmux-manager"),
        "homebrew-tap": Path("/p/homebrew-tap"),
        "tm": Path("/p/tm"),
    }
    assert [n for n, _ in match_projects(projects, "")] == ["tmux-manager", "homebrew-tap", "tm"]
    names = [n for n, _ in match_projects(projects, "tm")]
    assert names[0] == "tm"
    assert "tmux-manager" in names
    assert "homebrew-tap" not in names
    assert match_projects(projects, "zzz") == []


def names_shown(app: TmuxManagerApp) -> list[str]:
    option_list = app.screen.query_one(OptionList)
    return [str(option_list.get_option_at_index(i).id) for i in range(option_list.option_count)]


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
        assert names_shown(app) == ["alpha", "gamma"]
        assert str(option_list.get_option_at_index(0).prompt).startswith("● alpha")
        assert str(option_list.get_option_at_index(1).prompt).startswith("  gamma")
        assert app.screen.query_one(Input).has_focus


async def test_sessionizer_creates_missing_session(fake_tmux: FakeTmux, tmp_path: Path) -> None:
    (tmp_path / "alpha").mkdir()
    (tmp_path / "gamma").mkdir()
    app = TmuxManagerApp(config=Config(project_roots=(tmp_path,)))
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("p")
        await pilot.pause()
        await pilot.press("down", "enter")
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


async def test_sessionizer_filter_narrows_and_enter_picks_best(
    fake_tmux: FakeTmux, tmp_path: Path
) -> None:
    for name in ("alpha", "gamma", "delta"):
        (tmp_path / name).mkdir()
    app = TmuxManagerApp(config=Config(project_roots=(tmp_path,)))
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("p")
        await pilot.pause()
        await pilot.press("g", "a", "m")
        assert names_shown(app) == ["gamma"]
        await pilot.press("escape")  # first escape only clears the filter
        assert names_shown(app) == ["alpha", "delta", "gamma"]
        await pilot.press("d", "e", "l", "enter")
    assert fake_tmux.calls == [("new", "delta", str(tmp_path / "delta"))]
    assert app.return_value == PostAction(kind="attach", target="delta")


async def test_sessionizer_escape_returns_to_list(fake_tmux: FakeTmux, tmp_path: Path) -> None:
    app = TmuxManagerApp(config=Config(project_roots=(tmp_path,)))
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("p")
        await pilot.pause()
        hint = str(app.screen.query_one("#sessionizer-hint").visual)
        assert "No project directories found" in hint
        await pilot.press("escape")
        await pilot.pause()
        assert app.screen.query("#sessions")
