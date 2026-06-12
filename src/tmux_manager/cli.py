from __future__ import annotations

import argparse
import os
import sys

from . import __version__, tmux
from .app import TmuxManagerApp
from .config import load_config
from .models import PostAction

EPILOG = """\
keys:
  j/k, arrows     move cursor
  enter           attach (outside tmux) / switch client (inside tmux)
  n               new session
  d               kill session (with confirmation)
  r               rename session
  D               detach all clients from session
  p               project sessionizer
  /               filter session list
  q, escape       quit

configuration:
  ~/.config/tmux-manager/config.toml (see man tm or the README)
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tm",
        description="Interactive terminal UI for managing tmux sessions: "
        "overview with live preview, attach/switch, create, kill, rename, "
        "detach clients, and a project sessionizer.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    return parser


def main() -> None:
    build_parser().parse_args()
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
