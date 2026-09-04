from __future__ import annotations

import argparse
import os
import shutil
import sys

from . import __version__, tmux
from .config import Config, ConfigError, load_config
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
  s               sort by name / last activity
  v               show / hide the preview
  ?               key help
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
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def fail(message: str, code: int = 1) -> None:
    print(f"tm: {message}", file=sys.stderr)
    sys.exit(code)


def run_tui(config: Config) -> PostAction | None:
    # Imported lazily: Textual takes a noticeable moment to import and is
    # only needed when the interactive UI actually runs.
    from .app import TmuxManagerApp

    result: PostAction | None = TmuxManagerApp(config=config).run()
    return result


def perform(action: PostAction) -> None:
    """Attach or switch after the terminal has been restored."""
    if action.kind == "attach":
        # exec so tm leaves no extra process behind
        argv = tmux.base_argv() + ["attach-session", "-t", f"={action.target}"]
        os.execvp(argv[0], argv)
    else:
        try:
            tmux.switch_client(action.target)
        except tmux.TmuxError as error:
            fail(str(error))


def main(argv: list[str] | None = None) -> None:
    build_parser().parse_args(argv)
    if shutil.which("tmux") is None:
        fail("tmux not found on PATH")
    try:
        config = load_config()
    except ConfigError as error:
        fail(f"config error: {error}", code=2)
    result = run_tui(config)
    if result is not None:
        perform(result)
