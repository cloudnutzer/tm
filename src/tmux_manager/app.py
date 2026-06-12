from __future__ import annotations

from textual.app import App

from .config import Config
from .models import PostAction
from .screens.sessions import SessionsScreen


class TmuxManagerApp(App[PostAction]):
    TITLE = "tmux manager"
    CSS_PATH = "styles.tcss"

    def __init__(self, config: Config) -> None:
        super().__init__()
        self.cfg = config

    def on_mount(self) -> None:
        self.push_screen(SessionsScreen())
