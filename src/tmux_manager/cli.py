from __future__ import annotations

import os
import sys

from . import tmux
from .app import TmuxManagerApp
from .config import load_config
from .models import PostAction


def main() -> None:
    app = TmuxManagerApp(config=load_config())
    result: PostAction | None = app.run()
    if result is None:
        return
    if result.kind == "attach":
        # exec only after Textual has fully restored the terminal
        argv = tmux.base_argv() + ["attach-session", "-t", f"={result.target}"]
        os.execvp(argv[0], argv)
    else:
        try:
            tmux.switch_client(result.target)
        except tmux.TmuxError as error:
            sys.exit(f"tm: {error}")
