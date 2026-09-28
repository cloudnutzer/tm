from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.events import Resize
from textual.screen import Screen
from textual.timer import Timer
from textual.widgets import DataTable, Footer, Header, Input, Static

from .. import agents, tmux
from ..agents import STATE_ICONS, AgentStatus
from ..config import Config
from ..util import relative_time, short_path
from .modals import HelpModal
from .widgets import FilterInput, tail_of_pane

if TYPE_CHECKING:
    from ..app import TmuxManagerApp

PREVIEW_DEBOUNCE_SECONDS = 0.08
MIN_WIDTH_FOR_PREVIEW = 80

Row = tuple[str, str, str, str, str, str]

HELP = [
    ("j / k, ↓ / ↑", "move the cursor"),
    ("Enter", "jump to the agent's pane (attach or switch client)"),
    ("/", "filter agents; Esc clears, Enter jumps to the match"),
    ("?", "this help"),
    ("Esc", "clear the filter, then back to the session list"),
    ("", ""),
    ("🔴 blocked", "the agent waits for you: permission prompt, question"),
    ("🟢 working", "its pane changed in the last few seconds"),
    ("⚪ idle", "waiting for a new prompt"),
]


class AgentsScreen(Screen[None]):
    """One row per coding agent pane, the ones that need you first."""

    BINDINGS = [
        Binding("j", "cursor_down", "down", show=False),
        Binding("k", "cursor_up", "up", show=False),
        Binding("/", "filter", "filter"),
        Binding("question_mark", "help", "help", priority=True),
        Binding("escape", "back", "back"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._statuses: list[AgentStatus] = []
        self._loaded = False
        self._filter = ""
        self._last_rows: list[Row] | None = None
        self._preview_pane: str | None = None
        self._preview_raw = ""
        self._last_error: str | None = None
        self._list_timer: Timer | None = None
        self._preview_timer: Timer | None = None
        self._preview_debounce: Timer | None = None

    @property
    def cfg(self) -> Config:
        return cast("TmuxManagerApp", self.app).cfg

    def compose(self) -> ComposeResult:
        yield Header()
        yield FilterInput(placeholder="filter agents…", id="filter")
        with Horizontal(id="main"):
            yield DataTable(id="agents")
            yield Static(id="preview")
        yield Static(id="empty")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#preview").styles.width = f"{self.cfg.preview_width}%"
        self._apply_preview_visibility()
        table = self.query_one(DataTable)
        table.cursor_type = "row"
        table.add_columns("State", "Agent", "Session", "Window", "Path", "Changed")
        table.focus()
        self._list_timer = self.set_interval(self.cfg.list_refresh_seconds, self.refresh_agents)
        self._preview_timer = self.set_interval(
            self.cfg.preview_refresh_seconds, self.update_preview
        )
        self._update_status([])
        self.refresh_agents()

    def on_screen_suspend(self) -> None:
        for timer in (self._list_timer, self._preview_timer):
            if timer is not None:
                timer.pause()

    def on_screen_resume(self) -> None:
        if self._list_timer is None or self._preview_timer is None:
            return
        self._list_timer.resume()
        self._preview_timer.resume()
        self.refresh_agents()

    def on_resize(self, event: Resize) -> None:
        self._apply_preview_visibility()
        self._render_preview()

    # ------------------------------------------------------------- listing

    def refresh_agents(self) -> None:
        self._load_agents()

    @work(exclusive=True, group="agents")
    async def _load_agents(self) -> None:
        tracker = cast("TmuxManagerApp", self.app).agent_tracker
        try:
            statuses = await asyncio.to_thread(agents.collect, tracker)
        except tmux.TmuxError as error:
            message = str(error)
            if message != self._last_error and self._ui_alive():
                self._last_error = message
                self.notify(message, severity="error")
            return
        if not self._ui_alive():
            return
        self._last_error = None
        self._statuses = statuses
        self._loaded = True
        self._render_table()

    def _ui_alive(self) -> bool:
        return self.is_attached and bool(self.query(DataTable))

    def _visible(self) -> list[AgentStatus]:
        if not self._filter:
            return self._statuses
        needle = self._filter.lower()
        return [
            s
            for s in self._statuses
            if needle
            in " ".join(
                (s.state, s.agent, s.pane.session, s.pane.window_name, s.pane.current_path)
            ).lower()
        ]

    def _render_table(self) -> None:
        visible = self._visible()
        self._update_status(visible)
        rows = [agent_row(s) for s in visible]
        if rows == self._last_rows:
            return
        self._last_rows = rows
        table = self.query_one(DataTable)
        wanted = self._cursor_pane()
        previous_row = table.cursor_row
        table.clear()
        for status, row in zip(visible, rows, strict=True):
            table.add_row(*row, key=status.pane.pane_id)
        ids = [s.pane.pane_id for s in visible]
        if wanted in ids:
            table.move_cursor(row=ids.index(wanted))
        elif ids:
            table.move_cursor(row=min(previous_row, len(ids) - 1))
        self._schedule_preview()

    def _update_status(self, visible: list[AgentStatus]) -> None:
        count = len(self._statuses)
        summary = agents.rollup(self._statuses)
        self.sub_title = f"{count} agent{'s' if count != 1 else ''}" + (
            f" · {summary}" if summary else ""
        )
        if not self._loaded:
            message = "Looking for coding agents…"
        elif not self._statuses:
            message = "No coding agents found in any tmux pane — Esc goes back"
        elif not visible:
            message = f"No agents match '{self._filter}'"
        else:
            message = ""
        empty = self.query_one("#empty", Static)
        empty.update(message)
        empty.display = bool(message)
        self.query_one("#main").display = not message

    def _cursor_pane(self) -> str | None:
        table = self.query_one(DataTable)
        if not table.row_count:
            return None
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        return row_key.value

    def _status(self, pane_id: str | None) -> AgentStatus | None:
        return next((s for s in self._statuses if s.pane.pane_id == pane_id), None)

    # ------------------------------------------------------------- preview

    def _preview_visible(self) -> bool:
        return self.cfg.show_preview and self.size.width >= MIN_WIDTH_FOR_PREVIEW

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

    @work(exclusive=True, group="agent-preview")
    async def _load_preview(self) -> None:
        if not self._preview_visible():
            return
        pane_id = self._cursor_pane()
        content = ""
        if pane_id is not None:
            try:
                content = await asyncio.to_thread(tmux.capture_pane_by_id, pane_id, colors=True)
            except tmux.TmuxError:
                content = ""
        if not self._ui_alive() or pane_id != self._cursor_pane():
            return
        self._preview_pane = pane_id
        self._preview_raw = content
        self._render_preview()

    def _render_preview(self) -> None:
        preview = self.query_one("#preview", Static)
        status = self._status(self._preview_pane)
        preview.border_title = (
            f"{status.pane.session}:{status.pane.window_index}.{status.pane.pane_index}"
            f"  {status.agent}"
            if status
            else ""
        )
        preview.update(tail_of_pane(self._preview_raw, preview.content_size.height))

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self._schedule_preview()

    # ---------------------------------------------------------------- jump

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self._jump(event.row_key.value)

    def _jump(self, pane_id: str | None) -> None:
        status = self._status(pane_id)
        if status is not None:
            self.app.exit(tmux.pane_action(status.pane))

    # -------------------------------------------------- navigation/filter

    def action_help(self) -> None:
        self.app.push_screen(HelpModal("Agents", HELP))

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
        self._jump(self._cursor_pane())

    def action_back(self) -> None:
        filter_input = self.query_one("#filter", Input)
        if filter_input.display:
            filter_input.value = ""
            self._filter = ""
            filter_input.display = False
            self._render_table()
            self.query_one(DataTable).focus()
        else:
            self.app.pop_screen()


def agent_row(status: AgentStatus) -> Row:
    pane = status.pane
    window = f"{pane.window_index}"
    if pane.window_panes > 1:
        window += f".{pane.pane_index}"
    return (
        f"{STATE_ICONS[status.state]} {status.state}",
        status.agent,
        pane.session,
        f"{window}:{pane.window_name}" if pane.window_name else window,
        short_path(pane.current_path),
        relative_time(status.last_change),
    )
