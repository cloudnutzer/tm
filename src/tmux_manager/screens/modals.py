from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static

from .. import tmux
from ..models import NewSessionRequest


class ConfirmModal(ModalScreen[bool]):
    BINDINGS = [
        Binding("y", "confirm", "yes"),
        Binding("n", "cancel", "no"),
        Binding("escape", "cancel", "cancel", show=False),
    ]

    def __init__(self, message: str) -> None:
        super().__init__()
        self._message = message

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-box"):
            yield Label(self._message, classes="modal-message")
            with Horizontal(classes="modal-buttons"):
                yield Button("Yes (y)", variant="error", id="yes")
                yield Button("No (n)", id="no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class NewSessionModal(ModalScreen[NewSessionRequest | None]):
    BINDINGS = [Binding("escape", "cancel", "cancel", show=False)]

    def __init__(self, default_dir: str) -> None:
        super().__init__()
        self._default_dir = default_dir

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-box"):
            yield Label("New session", classes="modal-title")
            yield Input(placeholder="session name", id="name")
            yield Input(placeholder=f"start directory (default: {self._default_dir})", id="dir")
            yield Static("", id="error", classes="modal-error")
            with Horizontal(classes="modal-buttons"):
                yield Button("Create", variant="primary", id="create")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#name", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "create":
            self._submit()
        else:
            self.dismiss(None)

    def _submit(self) -> None:
        error = self.query_one("#error", Static)
        try:
            name = tmux.sanitize_session_name(self.query_one("#name", Input).value)
        except ValueError:
            error.update("Please enter a session name.")
            return
        raw_dir = self.query_one("#dir", Input).value.strip() or self._default_dir
        start_dir = Path(raw_dir).expanduser()
        if not start_dir.is_dir():
            error.update(f"Not a directory: {raw_dir}")
            return
        self.dismiss(NewSessionRequest(name=name, start_dir=str(start_dir)))

    def action_cancel(self) -> None:
        self.dismiss(None)


class RenameModal(ModalScreen[str | None]):
    BINDINGS = [Binding("escape", "cancel", "cancel", show=False)]

    def __init__(self, current: str) -> None:
        super().__init__()
        self._current = current

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-box"):
            yield Label(f"Rename session '{self._current}'", classes="modal-title")
            yield Input(value=self._current, id="name")
            yield Static("", id="error", classes="modal-error")
            with Horizontal(classes="modal-buttons"):
                yield Button("Rename", variant="primary", id="rename")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#name", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "rename":
            self._submit()
        else:
            self.dismiss(None)

    def _submit(self) -> None:
        try:
            name = tmux.sanitize_session_name(self.query_one("#name", Input).value)
        except ValueError:
            self.query_one("#error", Static).update("Please enter a session name.")
            return
        self.dismiss(name)

    def action_cancel(self) -> None:
        self.dismiss(None)
