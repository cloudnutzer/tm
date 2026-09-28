"""Which coding agent runs in which tmux pane.

``pane_current_command`` is not enough to tell: Claude Code, for example,
shows up as its version (``2.1.281``) because its binary is named after the
version. Instead the process table is read once per refresh, the process tree
below each pane's ``pane_pid`` is walked, and argv0 (falling back to the
kernel's command name) is matched against the known agent names. Agents that
run inside a runtime (``node /x/bin/codex``) are recognised by their script.

``read_processes()`` is the only function here that starts a subprocess, so
tests replace it with a fake just like ``tmux.py``.
"""

from __future__ import annotations

import subprocess
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, replace

from .models import TmuxPane

# Agent id (the herdr manifest id) -> executable names and aliases.
# Taken from herdr's lookup table (src/detect/mod.rs); agents without a screen
# manifest (omp, mastracode) are still detected and get activity-only state.
AGENT_NAMES: dict[str, tuple[str, ...]] = {
    "pi": ("pi",),
    "claude": ("claude", "claude-code"),
    "codex": ("codex",),
    "gemini": ("gemini",),
    "cursor": ("cursor", "cursor-agent"),
    "devin": ("devin", "devin-cli"),
    "agy": ("agy", "antigravity", "antigravity-cli"),
    "cline": ("cline", ".cline"),
    "omp": ("omp",),
    "mastracode": ("mastracode", "mastra-code"),
    "opencode": ("opencode", "opencode2", "open-code"),
    "copilot": ("copilot", "github-copilot", "ghcs"),
    "kimi": ("kimi", "kimi-code"),
    "kiro": ("kiro", "kiro-cli"),
    "droid": ("droid",),
    "amp": ("amp", "amp-local"),
    "grok": ("grok", "grok-build"),
    "hermes": ("hermes", "hermes-agent"),
    "kilo": ("kilo", "kilo-code"),
    "qodercli": ("qodercli", "qoderclicn", "qoder", "qodercn"),
    "qwen": ("qwen", "qwen-code"),
    "letta": ("letta", "letta-code"),
    "maki": ("maki",),
    "muse": ("muse", "muse-code", "muse-cli"),
}

_SHELLS = frozenset({"sh", "bash", "zsh", "fish", "dash", "ksh"})
_JS_RUNTIMES = frozenset({"node", "bun", "deno"})
# Arguments after which the runtime runs inline code or a module, not a script.
_INLINE_FLAGS = frozenset({"-e", "--eval", "-p", "--print", "-c", "-m"})
# Runtime options that consume the next argument.
_OPTIONS_WITH_VALUE = frozenset(
    {"-r", "--require", "--loader", "--import", "--experimental-loader", "-W", "-X"}
)
_SUFFIXES = (".exe", ".cmd", ".bat", ".ps1", ".js", ".mjs", ".cjs")


@dataclass(frozen=True)
class Process:
    pid: int
    ppid: int
    comm: str
    """Kernel command name (on macOS the executable path)."""
    args: str
    """Full command line, argv joined by spaces."""


def read_processes() -> list[Process]:
    """Snapshot of the process table.

    Two ``ps`` calls because a combined ``comm=,args=`` line cannot be split
    reliably: macOS pads and truncates ``comm`` to 16 characters there, and
    either field may contain spaces. As the last column each is complete.
    """
    args = _parse_args(_ps("pid=,args="))
    processes = []
    for line in _ps("pid=,ppid=,comm="):
        fields = line.split(None, 2)
        if len(fields) < 2 or not (fields[0].isdigit() and fields[1].isdigit()):
            continue
        pid = int(fields[0])
        comm = fields[2] if len(fields) > 2 else ""
        processes.append(Process(pid=pid, ppid=int(fields[1]), comm=comm, args=args.get(pid, "")))
    return processes


def _ps(columns: str) -> list[str]:
    try:
        result = subprocess.run(
            ["ps", "-A", "-ww", "-o", columns], capture_output=True, text=True, check=False
        )
    except OSError:
        return []
    return result.stdout.splitlines()


def _parse_args(lines: Iterable[str]) -> dict[int, str]:
    parsed = {}
    for line in lines:
        pid, _, args = line.strip().partition(" ")
        if pid.isdigit():
            parsed[int(pid)] = args.strip()
    return parsed


def lookup_agent(name: str) -> str | None:
    """Agent id for an executable name or path, or None."""
    normalized = normalize_name(name)
    for agent, names in AGENT_NAMES.items():
        if normalized in names:
            return agent
    # Muse's launcher execs "muse-bin-<version>".
    if normalized.startswith("muse-bin-") and normalized[9:10].isdigit():
        return "muse"
    return None


def normalize_name(name: str) -> str:
    base = basename(name.strip().strip("\"'")).lower()
    for suffix in _SUFFIXES:
        if base.endswith(suffix):
            return base[: -len(suffix)]
    return base


def basename(path: str) -> str:
    parts = [part for part in path.replace("\\", "/").split("/") if part]
    return parts[-1] if parts else path


def _is_runtime(name: str) -> bool:
    if name in _SHELLS or name in _JS_RUNTIMES:
        return True
    if not name.startswith("python"):
        return False
    version = name[len("python") :]
    return not version or all(part.isdigit() for part in version.split("."))


def _script_agent(argv: list[str]) -> str | None:
    """The agent a runtime runs as its script, e.g. ``node /x/bin/codex``."""
    args = iter(argv[1:])
    for arg in args:
        if arg == "--":
            script = next(args, "")
            return lookup_agent(script) if script else None
        if arg in _INLINE_FLAGS or any(arg.startswith(f"{flag}=") for flag in _INLINE_FLAGS):
            return None
        if arg.startswith("-"):
            if arg in _OPTIONS_WITH_VALUE:
                next(args, None)
            continue
        return lookup_agent(arg)
    return None


def identify_process(process: Process) -> str | None:
    """Agent id of a single process, or None."""
    argv = process.args.split()
    argv0 = argv[0] if argv else process.comm
    name = normalize_name(argv0)
    if name and not name.startswith("-") and _is_runtime(name):
        return _script_agent(argv)
    agent = lookup_agent(argv0) if argv0 and not argv0.startswith("-") else None
    if agent is None and process.comm:
        agent = lookup_agent(process.comm)
    return agent


def pane_agent(pane_pid: int, processes: Iterable[Process]) -> str | None:
    """The agent running in a pane, searching its process tree breadth-first.

    The process closest to the pane wins, so the agent the user started beats
    anything that agent spawns itself (MCP servers, sub-agents).
    """
    return _tree_agent(pane_pid, *_index(processes))


def _index(processes: Iterable[Process]) -> tuple[dict[int, Process], dict[int, list[int]]]:
    by_pid: dict[int, Process] = {}
    children: dict[int, list[int]] = defaultdict(list)
    for process in processes:
        by_pid[process.pid] = process
        children[process.ppid].append(process.pid)
    return by_pid, children


def _tree_agent(
    root: int, by_pid: dict[int, Process], children: dict[int, list[int]]
) -> str | None:
    queue = [root]
    seen: set[int] = set()
    while queue:
        pid = queue.pop(0)
        if pid in seen:
            continue
        seen.add(pid)
        process = by_pid.get(pid)
        if process is not None:
            agent = identify_process(process)
            if agent is not None:
                return agent
        queue.extend(sorted(children.get(pid, ())))
    return None


def identify_panes(panes: Iterable[TmuxPane], processes: Iterable[Process]) -> list[TmuxPane]:
    """The panes with ``agent`` filled in from the process table."""
    by_pid, children = _index(processes)
    return [
        replace(pane, agent=_tree_agent(pane.pane_pid, by_pid, children)) if pane.pane_pid else pane
        for pane in panes
    ]
