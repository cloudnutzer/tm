from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, NoReturn

from . import __version__, agents, tmux
from .agents import STATE_ICONS, AgentStatus
from .config import Config, ConfigError, load_config
from .models import PostAction
from .util import relative_time, short_path

COMMANDS = ("open", "ls", "kill", "agents", "status")

EPILOG = """\
commands:
  tm                open the interactive session manager
  tm NAME           attach to session NAME, creating it in sessions.default_dir
  tm DIR            attach to the session for directory DIR, creating it there;
                    DIR must contain a "/" or be ".", ".." or start with "~"
  tm ls [--json]    list sessions (with their agents in --json)
  tm kill NAME      kill session NAME
  tm agents [--json]
                    list coding agents in tmux panes: blocked, working, idle
  tm status [--ascii]
                    one line for the tmux status bar, e.g. "🔴1 🟢2";
                    empty without agents

keys:
  j/k, arrows     move cursor
  enter           attach (outside tmux) / switch client (inside tmux)
  n               new session
  d               kill session (with confirmation)
  r               rename session
  D               detach all clients from session
  p               project sessionizer
  a               agents: coding agents in all panes, blocked first;
                  enter jumps to the agent's pane
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
        usage="%(prog)s [--help] [--version] "
        "[NAME | DIR | ls [--json] | kill NAME | agents [--json] | status [--ascii]]",
        description="Interactive terminal UI for managing tmux sessions: "
        "overview with live preview, attach/switch, create, kill, rename, "
        "detach clients, a project sessionizer, and the state of coding agents "
        "(Claude Code, Codex, OpenCode, ...) running in tmux panes. "
        "With a NAME or DIR argument, tm attaches directly without the UI.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", metavar="command")
    open_parser = commands.add_parser("open", help="attach to a session by name or directory")
    open_parser.add_argument("target", help="session name or project directory")
    ls_parser = commands.add_parser("ls", help="list sessions")
    ls_parser.add_argument("--json", action="store_true", help="machine-readable output")
    kill_parser = commands.add_parser("kill", help="kill a session")
    kill_parser.add_argument("name", help="exact session name")
    agents_parser = commands.add_parser("agents", help="list coding agents in tmux panes")
    agents_parser.add_argument("--json", action="store_true", help="machine-readable output")
    status_parser = commands.add_parser("status", help="agent summary for the tmux status bar")
    status_parser.add_argument(
        "--ascii", action="store_true", help="letters instead of emoji (B1 W2 I1)"
    )
    return parser


def normalize_argv(argv: list[str]) -> list[str]:
    """``tm foo`` is shorthand for ``tm open foo``."""
    if argv and not argv[0].startswith("-") and argv[0] not in COMMANDS:
        return ["open", *argv]
    return list(argv)


def fail(message: str, code: int = 1) -> NoReturn:
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
    if action.pane is not None:
        try:
            tmux.select_pane(action.pane)
        except tmux.TmuxError as error:
            fail(str(error))
    if action.kind == "attach":
        # exec so tm leaves no extra process behind
        argv = tmux.base_argv() + ["attach-session", "-t", f"={action.target}"]
        os.execvp(argv[0], argv)
    else:
        try:
            tmux.switch_client(action.target)
        except tmux.TmuxError as error:
            fail(str(error))


def looks_like_path(target: str) -> bool:
    return "/" in target or target in (".", "..") or target.startswith("~")


def open_target(target: str, config: Config) -> PostAction:
    """Resolve NAME or DIR to a session, creating it if needed."""
    if looks_like_path(target):
        directory = Path(target).expanduser().resolve()
        if not directory.is_dir():
            fail(f"not a directory: {target}")
        raw_name, start_dir = directory.name, str(directory)
    else:
        raw_name, start_dir = target, str(Path(config.default_dir).expanduser())
    try:
        name = tmux.sanitize_session_name(raw_name)
    except ValueError:
        fail(f"cannot derive a session name from '{target}'")
    try:
        if not tmux.has_session(name):
            tmux.new_session(name, start_dir)
    except tmux.TmuxError as error:
        fail(str(error))
    return tmux.attach_action(name)


def sample_agents(config: Config) -> list[AgentStatus]:
    try:
        return agents.sample(config.working_grace_seconds)
    except tmux.TmuxError as error:
        fail(str(error))


def agent_record(status: AgentStatus, now: int) -> dict[str, Any]:
    pane = status.pane
    return {
        "session": pane.session,
        "window": pane.window_index,
        "window_name": pane.window_name,
        "pane": pane.pane_index,
        "pane_id": pane.pane_id,
        "agent": status.agent,
        "state": status.state,
        "path": pane.current_path,
        "title": pane.title,
        "seconds_since_change": max(0, now - status.last_change),
    }


def print_sessions(as_json: bool, config: Config) -> None:
    try:
        sessions = tmux.list_sessions()
    except tmux.TmuxError as error:
        fail(str(error))
    if as_json:
        statuses = sample_agents(config) if sessions else []
        now = int(time.time())
        records = [
            {
                **asdict(s),
                "agents": [agent_record(a, now) for a in statuses if a.pane.session == s.name],
            }
            for s in sessions
        ]
        print(json.dumps(records, indent=2, ensure_ascii=False))
        return
    rows = [
        (
            s.name,
            str(s.windows),
            str(s.attached),
            relative_time(s.activity),
            short_path(s.current_path),
        )
        for s in sessions
    ]
    if sys.stdout.isatty():
        rows.insert(0, ("NAME", "WINDOWS", "CLIENTS", "ACTIVITY", "PATH"))
    widths = [max(len(row[i]) for row in rows) for i in range(4)] if rows else []
    for row in rows:
        print("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row[:4])) + "  " + row[4])


def print_agents(as_json: bool, config: Config) -> None:
    statuses = sample_agents(config)
    now = int(time.time())
    if as_json:
        records = [agent_record(s, now) for s in statuses]
        print(json.dumps(records, indent=2, ensure_ascii=False))
        return
    rows = [
        (
            f"{STATE_ICONS[s.state]} {s.state}",
            s.agent,
            f"{s.pane.session}:{s.pane.window_index}.{s.pane.pane_index}",
            s.pane.pane_id,
            relative_time(s.last_change, now),
            short_path(s.pane.current_path),
        )
        for s in statuses
    ]
    if sys.stdout.isatty():
        rows.insert(0, ("STATE", "AGENT", "TARGET", "PANE", "CHANGED", "PATH"))
    widths = [max(len(row[i]) for row in rows) for i in range(5)] if rows else []
    for row in rows:
        print("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row[:5])) + "  " + row[5])


def print_status(ascii: bool, config: Config) -> None:
    line = agents.rollup(sample_agents(config), ascii=ascii)
    if line:
        print(line)


def kill(name: str) -> None:
    try:
        tmux.kill_session(name)
    except tmux.TmuxError as error:
        fail(str(error))


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(normalize_argv(sys.argv[1:] if argv is None else argv))
    if shutil.which("tmux") is None:
        fail("tmux not found on PATH")
    try:
        config = load_config()
    except ConfigError as error:
        fail(f"config error: {error}", code=2)
    if args.command == "ls":
        print_sessions(as_json=args.json, config=config)
    elif args.command == "agents":
        print_agents(as_json=args.json, config=config)
    elif args.command == "status":
        print_status(ascii=args.ascii, config=config)
    elif args.command == "kill":
        kill(args.name)
    elif args.command == "open":
        perform(open_target(args.target, config))
    else:
        result = run_tui(config)
        if result is not None:
            perform(result)
