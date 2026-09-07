from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.events import Resize
from textual.screen import Screen
from textual.timer import Timer
from textual.widgets import DataTable, Footer, Header, Input, Static

from .. import tmux
from ..config import Config, SortMode
from ..models import TmuxSession
from ..util import relative_time, short_path
from .modals import ConfirmModal, HelpModal, NewSessionModal, RenameModal
from .sessionizer import SessionizerScreen
from .widgets import FilterInput

if TYPE_CHECKING:
    from ..app import TmuxManagerApp

# Cursor movements within this window only trigger one capture-pane call.
PREVIEW_DEBOUNCE_SECONDS = 0.08
# Below this terminal width the preview is hidden so the table stays usable.
MIN_WIDTH_FOR_PREVIEW = 80
CURRENT_MARKER = "▸"
POPUP_BINDING_EXAMPLE = "bind S display-popup -E -w 80% -h 75% tm"

Cell = str | Text
Row = tuple[Cell, Cell, Cell, Cell, Cell]

HELP = [
    ("j / k, ↓ / ↑", "move the cursor"),
    ("Enter", "attach (outside tmux) / switch client (inside tmux)"),
    ("n", "new session"),
    ("d", "kill session (asks first)"),
    ("r", "rename session"),
    ("D", "detach all clients from session"),
    ("p", "project sessionizer"),
    ("/", "filter sessions; Esc clears, Enter jumps to the match"),
    ("s", "sort by name / last activity"),
    ("v", "show / hide the preview"),
    ("?", "this help"),
    ("q, Esc", "quit"),
]


class SessionsScreen(Screen[None]):
    BINDINGS = [
        Binding("j", "cursor_down", "down", show=False),
        Binding("k", "cursor_up", "up", show=False),
        Binding("n", "new_session", "new"),
        Binding("d", "kill_session", "delete"),
        Binding("r", "rename_session", "rename"),
        Binding("D", "detach_clients", "detach"),
        Binding("p", "sessionizer", "projects"),
        Binding("/", "filter", "filter"),
        Binding("s", "toggle_sort", "sort"),
        Binding("v", "toggle_preview", "preview"),
        Binding("question_mark", "help", "help", priority=True),
        Binding("escape", "escape", "close", show=False),
        Binding("q", "app.quit", "quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._sessions: list[TmuxSession] = []
        self._current: str | None = None
        self._inside = False
        self._popup_key: str | None = None
        self._popup_checked = False
        self._filter = ""
        self._cursor_target: str | None = None
        self._sort: SortMode = "name"
        self._show_preview = True
        self._last_rows: list[Row] | None = None
        self._preview_name: str | None = None
        self._preview_raw = ""
        self._last_preview: tuple[str, int, str] | None = None
        self._last_error: str | None = None
        self._list_timer: Timer | None = None
        self._preview_timer: Timer | None = None
        self._preview_debounce: Timer | None = None

    @property
    def cfg(self) -> Config:
        return cast("TmuxManagerApp", self.app).cfg

    def compose(self) -> ComposeResult:
        yield Header()
        yield FilterInput(placeholder="filter sessions…", id="filter")
        with Horizontal(id="main"):
            yield DataTable(id="sessions")
            yield Static(id="preview")
        yield Static(id="empty")
        yield Static(id="hint")
        yield Footer()

    def on_mount(self) -> None:
        self._sort = self.cfg.sort
        self._show_preview = self.cfg.show_preview
        self.query_one("#preview").styles.width = f"{self.cfg.preview_width}%"
        self._apply_preview_visibility()
        table = self.query_one(DataTable)
        table.cursor_type = "row"
        table.add_columns("Name", "Windows", "Clients", "Activity", "Path")
        table.focus()
        self._list_timer = self.set_interval(self.cfg.list_refresh_seconds, self.refresh_sessions)
        self._preview_timer = self.set_interval(
            self.cfg.preview_refresh_seconds, self.update_preview
        )
        self.refresh_sessions()

    # Timers only run while this screen is visible; a modal or the
    # sessionizer on top suspends it.
    def on_screen_suspend(self) -> None:
        for timer in (self._list_timer, self._preview_timer):
            if timer is not None:
                timer.pause()

    def on_screen_resume(self) -> None:
        if self._list_timer is None or self._preview_timer is None:
            return  # resume before mount: on_mount does the initial refresh
        self._list_timer.resume()
        self._preview_timer.resume()
        self.refresh_sessions()

    def on_resize(self, event: Resize) -> None:
        self._apply_preview_visibility()
        self._render_preview()

    # ------------------------------------------------------------- listing

    def refresh_sessions(self) -> None:
        self._load_sessions()

    @work(exclusive=True, group="sessions")
    async def _load_sessions(self) -> None:
        check_popup = not self._popup_checked

        def load() -> tuple[list[TmuxSession], str | None, str | None]:
            sessions = tmux.list_sessions()
            popup = tmux.popup_binding() if check_popup else self._popup_key
            return sessions, tmux.current_session(), popup

        try:
            sessions, current, popup = await asyncio.to_thread(load)
        except tmux.TmuxError as error:
            self._report_error(str(error))
            return
        self._last_error = None
        self._sessions = sessions
        self._inside = tmux.inside_tmux()
        self._current = current
        self._popup_key = popup
        self._popup_checked = True
        self._render_table()

    def _report_error(self, message: str) -> None:
        # A persistent failure must not raise a notification every tick.
        if message != self._last_error:
            self._last_error = message
            self.notify(message, severity="error")

    def _visible_sessions(self) -> list[TmuxSession]:
        sessions = self._sessions
        if self._filter:
            needle = self._filter.lower()
            sessions = [s for s in sessions if needle in s.name.lower()]
        if self._sort == "activity":
            return sorted(sessions, key=lambda s: s.activity, reverse=True)
        return sorted(sessions, key=lambda s: s.name.lower())

    def _row(self, session: TmuxSession) -> Row:
        if self._current is None:
            name: Cell = session.name
        elif session.name == self._current:
            name = Text(f"{CURRENT_MARKER} {session.name}", style="bold")
        else:
            name = f"  {session.name}"
        return (
            name,
            str(session.windows),
            str(session.attached) if session.attached else "",
            relative_time(session.activity),
            short_path(session.current_path or session.path),
        )

    def _render_table(self) -> None:
        visible = self._visible_sessions()
        rows = [self._row(s) for s in visible]
        self._update_status(visible)
        if rows == self._last_rows:
            return
        self._last_rows = rows
        table = self.query_one(DataTable)
        wanted = self._cursor_target or self._cursor_session_name()
        previous_row = table.cursor_row
        table.clear()
        for session, row in zip(visible, rows, strict=True):
            table.add_row(*row, key=session.name)
        names = [s.name for s in visible]
        if wanted in names:
            table.move_cursor(row=names.index(wanted))
            self._cursor_target = None
        elif names:
            # e.g. the highlighted session was killed: stay on the same row
            table.move_cursor(row=min(previous_row, len(names) - 1))
        self._schedule_preview()

    def _update_status(self, visible: list[TmuxSession]) -> None:
        count = len(self._sessions)
        where = "inside tmux" if self._inside else "outside tmux"
        self.sub_title = f"{count} session{'s' if count != 1 else ''} · by {self._sort} · {where}"
        if not self._sessions:
            message = "No tmux sessions — press n to create one or p to pick a project"
        elif not visible:
            message = f"No sessions match '{self._filter}'"
        else:
            message = ""
        empty = self.query_one("#empty", Static)
        empty.update(message)
        empty.display = bool(message)
        self.query_one("#main").display = not message
        self.query_one("#hint", Static).update(
            Text(switch_hint(inside=self._inside, popup_key=self._popup_key))
        )

    def _cursor_session_name(self) -> str | None:
        table = self.query_one(DataTable)
        if not table.row_count:
            return None
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        return row_key.value

    def _session(self, name: str) -> TmuxSession | None:
        return next((s for s in self._sessions if s.name == name), None)

    # ------------------------------------------------------------- preview

    def _preview_visible(self) -> bool:
        return self._show_preview and self.size.width >= MIN_WIDTH_FOR_PREVIEW

    def _apply_preview_visibility(self) -> None:
        preview = self.query_one("#preview")
        visible = self._preview_visible()
        if preview.display != visible:
            preview.display = visible
            if visible:
                self._schedule_preview()

    def update_preview(self) -> None:
        self._load_preview()

    def _schedule_preview(self) -> None:
        if self._preview_debounce is not None:
            self._preview_debounce.stop()
        self._preview_debounce = self.set_timer(PREVIEW_DEBOUNCE_SECONDS, self.update_preview)

    @work(exclusive=True, group="preview")
    async def _load_preview(self) -> None:
        if not self._preview_visible():
            return
        name = self._cursor_session_name()
        if name is None:
            self._set_preview(None, "")
            return
        try:
            content = await asyncio.to_thread(tmux.capture_pane, name)
        except tmux.TmuxError:
            content = ""
        if name != self._cursor_session_name():
            return  # the cursor moved on while tmux was busy
        self._set_preview(name, content)

    def _set_preview(self, name: str | None, content: str) -> None:
        self._preview_name = name
        self._preview_raw = content
        self._render_preview()

    def _render_preview(self) -> None:
        preview = self.query_one("#preview", Static)
        height = preview.content_size.height
        title = ""
        if self._preview_name is not None:
            session = self._session(self._preview_name)
            command = f"  {session.command}" if session and session.command else ""
            title = f"{self._preview_name}{command}"
        key = (self._preview_raw, height, title)
        if key == self._last_preview:
            return
        self._last_preview = key
        preview.border_title = title
        preview.update(tail_of_pane(self._preview_raw, height))

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self._schedule_preview()

    # ------------------------------------------------------- attach/switch

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self._attach_session(event.row_key.value)

    # NOTE: must not be named "_attach" — that shadows MessagePump._attach,
    # which Textual uses internally to attach nodes to the DOM during mount.
    def _attach_session(self, name: str | None) -> None:
        if not name:
            return
        self.app.exit(tmux.attach_action(name))

    # ----------------------------------------------------------- mutations

    @work
    async def action_new_session(self) -> None:
        request = await self.app.push_screen_wait(NewSessionModal(default_dir=self.cfg.default_dir))
        if request is None:
            return
        try:
            tmux.new_session(request.name, request.start_dir)
        except tmux.TmuxError as error:
            self.notify(str(error), severity="error")
            return
        self._attach_session(request.name)

    @work
    async def action_kill_session(self) -> None:
        name = self._cursor_session_name()
        if name is None:
            return
        message = f"Kill session '{name}'?"
        if name == self._current:
            message += "\n\nYou are currently inside this session!"
        confirmed = await self.app.push_screen_wait(ConfirmModal(message))
        if not confirmed:
            return
        try:
            tmux.kill_session(name)
        except tmux.TmuxError as error:
            self.notify(str(error), severity="error")
        self.refresh_sessions()

    @work
    async def action_rename_session(self) -> None:
        name = self._cursor_session_name()
        if name is None:
            return
        new_name = await self.app.push_screen_wait(RenameModal(current=name))
        if not new_name or new_name == name:
            return
        self._cursor_target = new_name  # follow the session to its new name
        try:
            tmux.rename_session(name, new_name)
        except tmux.TmuxError as error:
            self._cursor_target = None
            self.notify(str(error), severity="error")
        self.refresh_sessions()

    @work
    async def action_detach_clients(self) -> None:
        name = self._cursor_session_name()
        if name is None:
            return
        confirmed = await self.app.push_screen_wait(
            ConfirmModal(f"Detach all clients from '{name}'?")
        )
        if not confirmed:
            return
        try:
            tmux.detach_clients(name)
        except tmux.TmuxError as error:
            self.notify(str(error), severity="error")
        self.refresh_sessions()

    # -------------------------------------------------- navigation/filter

    def action_sessionizer(self) -> None:
        self.app.push_screen(SessionizerScreen())

    def action_help(self) -> None:
        self.app.push_screen(HelpModal("Session list", HELP))

    def action_toggle_sort(self) -> None:
        self._sort = "activity" if self._sort == "name" else "name"
        self._render_table()

    def action_toggle_preview(self) -> None:
        self._show_preview = not self._show_preview
        self._apply_preview_visibility()
        if self._show_preview and self.size.width < MIN_WIDTH_FOR_PREVIEW:
            self.notify(
                f"Preview needs at least {MIN_WIDTH_FOR_PREVIEW} columns", severity="warning"
            )

    def action_cursor_down(self) -> None:
        self.query_one(DataTable).action_cursor_down()

    def action_cursor_up(self) -> None:
        self.query_one(DataTable).action_cursor_up()

    def action_filter(self) -> None:
        filter_input = self.query_one("#filter", Input)
        filter_input.display = True
        filter_input.focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        self._filter = event.value
        self._render_table()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.query_one(DataTable).focus()
        self._attach_session(self._cursor_session_name())

    def action_escape(self) -> None:
        filter_input = self.query_one("#filter", Input)
        if filter_input.display:
            filter_input.value = ""
            self._filter = ""
            filter_input.display = False
            self._render_table()
            self.query_one(DataTable).focus()
        else:
            self.app.exit(None)


def switch_hint(*, inside: bool, popup_key: str | None) -> str:
    """One line explaining how to switch sessions without detaching."""
    if inside:
        base = "Enter switches to the highlighted session — no need to detach."
        if popup_key:
            return f"{base} From any session, prefix {popup_key} opens this picker."
        return f"{base} To open it from any session, add to ~/.tmux.conf: {POPUP_BINDING_EXAMPLE}"
    if popup_key:
        return (
            f"Inside a session, prefix {popup_key} opens this picker — "
            "Enter switches, no need to detach."
        )
    return (
        "Inside a session, run tm again to switch — no need to detach. "
        f"For a popup key, add to ~/.tmux.conf: {POPUP_BINDING_EXAMPLE}"
    )


def tail_of_pane(content: str, height: int) -> Text:
    """The last ``height`` non-blank lines of a captured pane, colors intact.

    capture-pane returns the full pane height including the blank rows below
    the prompt; showing the top would hide the most recent output.
    """
    lines: list[Text] = list(Text.from_ansi(content).split("\n"))
    for line in lines:
        line.rstrip()
    while lines and not lines[-1].plain.strip():
        lines.pop()
    if height > 0:
        lines = lines[-height:]
    return Text("\n").join(lines)
