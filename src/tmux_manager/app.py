from __future__ import annotations

from textual.app import App

from .agents import AgentTracker
from .config import Config
from .models import PostAction
from .screens.sessions import SessionsScreen


class TmuxManagerApp(App[PostAction]):
    TITLE = "tmux manager"
    CSS_PATH = "styles.tcss"
    ENABLE_COMMAND_PALETTE = False

    def __init__(self, config: Config) -> None:
        super().__init__()
        self.cfg = config
        # Shared by the session list and the agents screen, so an agent's
        # activity history survives switching between them.
        self.agent_tracker = AgentTracker(config.working_grace_seconds)

    def on_mount(self) -> None:
        self.push_screen(SessionsScreen())
