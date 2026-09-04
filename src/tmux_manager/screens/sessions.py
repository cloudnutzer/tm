from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import Screen
from textual.timer import Timer
from textual.widgets import DataTable, Footer, Header, Input, Static

from .. import tmux
from ..config import Config
from ..models import TmuxSession
from ..util import relative_time, short_path
from .modals import ConfirmModal, NewSessionModal, RenameModal
from .sessionizer import SessionizerScreen

if TYPE_CHECKING:
    from ..app import TmuxManagerApp

# Cursor movements within this window only trigger one capture-pane call.
PREVIEW_DEBOUNCE_SECONDS = 0.08

Row = tuple[str, str, str, str, str]


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
        Binding("escape", "escape", "close", show=False),
        Binding("q", "app.quit", "quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._sessions: list[TmuxSession] = []
        self._filter = ""
        self._last_rows: list[Row] | None = None
        self._last_preview: str | None = None
        self._last_error: str | None = None
        self._list_timer: Timer | None = None
        self._preview_timer: Timer | None = None
        self._preview_debounce: Timer | None = None

    @property
    def cfg(self) -> Config:
        return cast("TmuxManagerApp", self.app).cfg

    def compose(self) -> ComposeResult:
        yield Header()
        yield Input(placeholder="filter sessions…", id="filter")
        with Horizontal(id="main"):
            yield DataTable(id="sessions")
            yield Static(id="preview")
        yield Static("No tmux sessions — press n to create one or p to pick a project", id="empty")
        yield Footer()

    def on_mount(self) -> None:
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

    # ------------------------------------------------------------- listing

    def refresh_sessions(self) -> None:
        self._load_sessions()

    @work(exclusive=True, group="sessions")
    async def _load_sessions(self) -> None:
        try:
            sessions = await asyncio.to_thread(tmux.list_sessions)
        except tmux.TmuxError as error:
            self._report_error(str(error))
            return
        self._last_error = None
        self._sessions = sessions
        self._render_table()

    def _report_error(self, message: str) -> None:
        # A persistent failure must not raise a notification every tick.
        if message != self._last_error:
            self._last_error = message
            self.notify(message, severity="error")

    def _visible_sessions(self) -> list[TmuxSession]:
        if not self._filter:
            return self._sessions
        needle = self._filter.lower()
        return [s for s in self._sessions if needle in s.name.lower()]

    @staticmethod
    def _row(session: TmuxSession) -> Row:
        return (
            session.name,
            str(session.windows),
            str(session.attached) if session.attached else "",
            relative_time(session.activity),
            short_path(session.current_path or session.path),
        )

    def _render_table(self) -> None:
        visible = self._visible_sessions()
        rows = [self._row(s) for s in visible]
        self._set_empty(not self._sessions)
        if rows == self._last_rows:
            return
        self._last_rows = rows
        table = self.query_one(DataTable)
        current = self._cursor_session_name()
        table.clear()
        for session, row in zip(visible, rows, strict=True):
            table.add_row(*row, key=session.name)
        if current is not None:
            names = [s.name for s in visible]
            if current in names:
                table.move_cursor(row=names.index(current))
        self._schedule_preview()

    def _set_empty(self, empty: bool) -> None:
        self.query_one("#main").display = not empty
        self.query_one("#empty").display = empty

    def _cursor_session_name(self) -> str | None:
        table = self.query_one(DataTable)
        if not table.row_count:
            return None
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        return row_key.value

    # ------------------------------------------------------------- preview

    def update_preview(self) -> None:
        self._load_preview()

    def _schedule_preview(self) -> None:
        if self._preview_debounce is not None:
            self._preview_debounce.stop()
        self._preview_debounce = self.set_timer(PREVIEW_DEBOUNCE_SECONDS, self.update_preview)

    @work(exclusive=True, group="preview")
    async def _load_preview(self) -> None:
        name = self._cursor_session_name()
        if name is None:
            self._set_preview("")
            return
        try:
            content = await asyncio.to_thread(tmux.capture_pane, name)
        except tmux.TmuxError:
            content = ""
        if name != self._cursor_session_name():
            return  # the cursor moved on while tmux was busy
        self._set_preview(content)

    def _set_preview(self, content: str) -> None:
        if content == self._last_preview:
            return
        self._last_preview = content
        self.query_one("#preview", Static).update(Text.from_ansi(content))

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
        if name == tmux.current_session():
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
        try:
            tmux.rename_session(name, new_name)
        except tmux.TmuxError as error:
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
