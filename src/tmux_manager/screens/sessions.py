from __future__ import annotations

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Input, Static

from .. import tmux
from ..models import PostAction, TmuxSession
from ..util import relative_time, short_path
from .modals import ConfirmModal, NewSessionModal, RenameModal
from .sessionizer import SessionizerScreen


class SessionsScreen(Screen):
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

    def compose(self) -> ComposeResult:
        yield Header()
        yield Input(placeholder="filter sessions…", id="filter")
        with Horizontal(id="main"):
            yield DataTable(id="sessions")
            yield Static(id="preview")
        yield Static(
            "No tmux sessions — press n to create one or p to pick a project", id="empty"
        )
        yield Footer()

    def on_mount(self) -> None:
        self._sessions: list[TmuxSession] = []
        self._filter = ""
        table = self.query_one(DataTable)
        table.cursor_type = "row"
        table.add_columns("Name", "Win", "Att", "Activity", "Path")
        self.refresh_sessions()
        cfg = self.app.cfg
        self.set_interval(cfg.list_refresh_seconds, self.refresh_sessions)
        self.set_interval(cfg.preview_refresh_seconds, self.update_preview)
        table.focus()

    # ------------------------------------------------------------- listing

    def refresh_sessions(self) -> None:
        try:
            self._sessions = tmux.list_sessions()
        except tmux.TmuxError as error:
            self.notify(str(error), severity="error")
            return
        self._render_table()
        self.update_preview()

    def _visible_sessions(self) -> list[TmuxSession]:
        if not self._filter:
            return self._sessions
        needle = self._filter.lower()
        return [s for s in self._sessions if needle in s.name.lower()]

    def _render_table(self) -> None:
        table = self.query_one(DataTable)
        current = self._cursor_session_name()
        visible = self._visible_sessions()
        table.clear()
        for session in visible:
            table.add_row(
                session.name,
                str(session.windows),
                "●" if session.attached else "",
                relative_time(session.activity),
                short_path(session.path),
                key=session.name,
            )
        self._set_empty(not self._sessions)
        if current is not None:
            names = [s.name for s in visible]
            if current in names:
                table.move_cursor(row=names.index(current))

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
        preview = self.query_one("#preview", Static)
        name = self._cursor_session_name()
        if name is None:
            preview.update("")
            return
        try:
            content = tmux.capture_pane(name)
        except tmux.TmuxError:
            preview.update("")
            return
        text = Text.from_ansi(content)
        text.no_wrap = True
        preview.update(text)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self.update_preview()

    # ------------------------------------------------------- attach/switch

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self._attach_session(event.row_key.value)

    # NOTE: must not be named "_attach" — that shadows MessagePump._attach,
    # which Textual uses internally to attach nodes to the DOM during mount.
    def _attach_session(self, name: str | None) -> None:
        if not name:
            return
        kind = "switch" if tmux.inside_tmux() else "attach"
        self.app.exit(PostAction(kind=kind, target=name))

    # ----------------------------------------------------------- mutations

    @work
    async def action_new_session(self) -> None:
        request = await self.app.push_screen_wait(
            NewSessionModal(default_dir=self.app.cfg.default_dir)
        )
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
