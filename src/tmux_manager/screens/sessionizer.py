from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, cast

from textual.app import ComposeResult
from textual.binding import Binding
from textual.content import Content
from textual.fuzzy import Matcher
from textual.screen import Screen
from textual.widgets import Footer, Header, Input, OptionList, Static
from textual.widgets.option_list import Option

from .. import tmux
from ..config import Config
from ..util import short_path
from .modals import HelpModal

if TYPE_CHECKING:
    from ..app import TmuxManagerApp

HELP = [
    ("type", "fuzzy-filter the projects"),
    ("↓ / ↑, ctrl+n / ctrl+p", "move the cursor"),
    ("Enter", "create the project's session, or attach if it exists (●)"),
    ("?", "this help"),
    ("Esc", "clear the filter, then back to the session list"),
]


class SessionizerScreen(Screen[None]):
    BINDINGS = [
        Binding("escape", "back", "back"),
        Binding("down,ctrl+n", "cursor_down", "down", show=False),
        Binding("up,ctrl+p", "cursor_up", "up", show=False),
        Binding("question_mark", "help", "help", priority=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._projects: dict[str, Path] = {}
        self._existing: set[str] = set()

    @property
    def cfg(self) -> Config:
        return cast("TmuxManagerApp", self.app).cfg

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            "Pick a project — type to filter, Enter creates or attaches its session",
            id="sessionizer-hint",
        )
        yield Input(placeholder="filter projects…", id="project-filter")
        yield OptionList(id="projects")
        yield Footer()

    def on_mount(self) -> None:
        self._projects = discover_projects(self.cfg.project_roots)
        if not self._projects:
            roots = ", ".join(str(r) for r in self.cfg.project_roots)
            self.query_one("#sessionizer-hint", Static).update(
                f"No project directories found in: {roots}"
            )
            self.query_one(Input).display = False
            return
        self._load_existing()
        self._render_options()
        self.query_one(Input).focus()

    def on_screen_resume(self) -> None:
        if self._projects:
            self._load_existing()
            self._render_options()

    def _load_existing(self) -> None:
        try:
            self._existing = {s.name for s in tmux.list_sessions()}
        except tmux.TmuxError:
            self._existing = set()

    def _render_options(self) -> None:
        option_list = self.query_one(OptionList)
        query = self.query_one(Input).value.strip()
        option_list.clear_options()
        for name, directory in match_projects(self._projects, query):
            marker = "● " if name in self._existing else "  "
            label = Matcher(query).highlight(name) if query else Content(name)
            option_list.add_option(
                Option(
                    Content.assemble(marker, label, (f"  {short_path(str(directory))}", "dim")),
                    id=name,
                )
            )
        if option_list.option_count:
            option_list.highlighted = 0

    def on_input_changed(self, event: Input.Changed) -> None:
        self._render_options()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.query_one(OptionList).action_select()

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
        self.app.exit(tmux.attach_action(name))

    def action_back(self) -> None:
        filter_input = self.query_one(Input)
        if filter_input.value:
            filter_input.value = ""
            return
        self.app.pop_screen()

    def action_help(self) -> None:
        self.app.push_screen(HelpModal("Project sessionizer", HELP))

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


def match_projects(projects: dict[str, Path], query: str) -> list[tuple[str, Path]]:
    """Projects matching the fuzzy query, best match first; all of them if empty."""
    if not query:
        return list(projects.items())
    matcher = Matcher(query)
    scored = [(matcher.match(name), name, path) for name, path in projects.items()]
    return [
        (name, path)
        for score, name, path in sorted(scored, key=lambda s: (-s[0], s[1]))
        if score > 0
    ]
