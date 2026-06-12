from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Footer, Header, OptionList, Static
from textual.widgets.option_list import Option

from .. import tmux
from ..models import PostAction
from ..util import short_path


class SessionizerScreen(Screen):
    BINDINGS = [
        Binding("escape", "back", "back"),
        Binding("q", "back", "back", show=False),
        Binding("j", "cursor_down", "down", show=False),
        Binding("k", "cursor_up", "up", show=False),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            "Pick a project — Enter creates or attaches its session", id="sessionizer-hint"
        )
        yield OptionList(id="projects")
        yield Footer()

    def on_mount(self) -> None:
        self._projects = discover_projects(self.app.cfg.project_roots)
        if not self._projects:
            roots = ", ".join(str(r) for r in self.app.cfg.project_roots)
            self.query_one("#sessionizer-hint", Static).update(
                f"No project directories found in: {roots}"
            )
            return
        try:
            existing = {s.name for s in tmux.list_sessions()}
        except tmux.TmuxError:
            existing = set()
        option_list = self.query_one(OptionList)
        for name, directory in self._projects.items():
            marker = "● " if name in existing else "  "
            option_list.add_option(Option(f"{marker}{name}  ({short_path(str(directory))})", id=name))
        option_list.highlighted = 0
        option_list.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        name = event.option.id
        if name is None:
            return
        directory = self._projects[name]
        try:
            if not tmux.has_session(name):
                tmux.new_session(name, str(directory))
        except tmux.TmuxError as error:
            self.notify(str(error), severity="error")
            return
        kind = "switch" if tmux.inside_tmux() else "attach"
        self.app.exit(PostAction(kind=kind, target=name))

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_cursor_down(self) -> None:
        self.query_one(OptionList).action_cursor_down()

    def action_cursor_up(self) -> None:
        self.query_one(OptionList).action_cursor_up()


def discover_projects(roots: tuple[Path, ...]) -> dict[str, Path]:
    """Direct subdirectories of all roots, keyed by sanitized session name."""
    projects: dict[str, Path] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for entry in sorted(root.iterdir()):
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            name = tmux.sanitize_session_name(entry.name)
            projects.setdefault(name, entry)
    return dict(sorted(projects.items()))
