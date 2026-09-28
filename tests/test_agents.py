import subprocess

import pytest

from tmux_manager import agents
from tmux_manager.agents import Process
from tmux_manager.models import TmuxPane


def pane(pane_id: str, pid: int, command: str = "zsh") -> TmuxPane:
    return TmuxPane(
        session="work",
        window_index=0,
        window_name="main",
        pane_index=int(pane_id[1:]),
        pane_id=pane_id,
        pane_pid=pid,
        command=command,
        current_path="/tmp",
        window_activity=0,
        window_panes=1,
        title="",
    )


PROCESSES = [
    Process(1, 0, "/sbin/launchd", "/sbin/launchd"),
    # %1: Claude Code; the binary is named after its version
    Process(100, 1, "-zsh", "-zsh"),
    Process(101, 100, "/Users/x/.local/share/claude/versions/2.1.281", "claude --model haiku"),
    Process(102, 101, "node", "node /Users/x/.npm/bin/firecrawl-mcp"),
    # %2: Codex, a node wrapper around the native binary
    Process(200, 1, "-zsh", "-zsh"),
    Process(201, 200, "node", "node /opt/homebrew/bin/codex --full-auto"),
    Process(202, 201, "codex", "/opt/homebrew/lib/node_modules/@openai/codex/vendor/codex"),
    # %3: a plain shell running vim
    Process(300, 1, "-zsh", "-zsh"),
    Process(301, 300, "vim", "vim notes.md"),
    # %4: an agent behind a runtime with options before the script
    Process(400, 1, "zsh", "zsh"),
    Process(401, 400, "bun", "bun --smol /x/node_modules/.bin/opencode.js"),
    # %5: python running inline code is not an agent even if it mentions one
    Process(500, 1, "zsh", "zsh"),
    Process(501, 500, "python3.12", "python3.12 -m claude"),
    # %6: the pane process itself is the agent (tmux new-window agy)
    Process(600, 1, "agy", "agy"),
]


@pytest.mark.parametrize(
    ("pid", "expected"),
    [(100, "claude"), (200, "codex"), (300, None), (400, "opencode"), (500, None), (600, "agy")],
)
def test_pane_agent(pid: int, expected: str | None) -> None:
    assert agents.pane_agent(pid, PROCESSES) == expected


def test_identify_panes_fills_in_agents() -> None:
    panes = [pane("%1", 100, "2.1.281"), pane("%2", 200, "node"), pane("%3", 300, "vim")]
    identified = agents.identify_panes(panes, PROCESSES)
    assert [p.agent for p in identified] == ["claude", "codex", None]
    assert identified[0].command == "2.1.281"


def test_identify_process_falls_back_to_comm() -> None:
    assert agents.identify_process(Process(1, 0, "/usr/local/bin/gemini", "")) == "gemini"
    assert agents.identify_process(Process(1, 0, "zsh", "")) is None


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("claude", "claude"),
        ("/Users/x/.local/bin/claude", "claude"),
        ("Claude-Code", "claude"),
        ("cursor-agent", "cursor"),
        ("antigravity", "agy"),
        ("kiro-cli", "kiro"),
        ("C:\\bin\\codex.exe", "codex"),
        ("muse-bin-0.1.0-R708.1", "muse"),
        ("muse-binary", None),
        ("2.1.281", None),
        ("zsh", None),
    ],
)
def test_lookup_agent(name: str, expected: str | None) -> None:
    assert agents.lookup_agent(name) == expected


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ("node /x/bin/qwen", "qwen"),
        ("node -r ts-node/register /x/cline.js", "cline"),
        ("node -- /x/bin/amp", "amp"),
        ("node --eval claude", None),
        ("node --print=1 claude", None),
        ("python3 /usr/bin/hermes", "hermes"),
        ("python3.12.1 /usr/bin/hermes", "hermes"),
        ("bash /usr/local/bin/droid", "droid"),
        ("node", None),
    ],
)
def test_runtime_wrappers(args: str, expected: str | None) -> None:
    assert agents.identify_process(Process(1, 0, args.split()[0], args)) == expected


def test_read_processes_merges_two_ps_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    outputs = {
        "pid=,ppid=,comm=": "    1     0 /sbin/launchd\n  101   100 /Applications/My App.app/x\n",
        "pid=,args=": "    1 /sbin/launchd\n  101 claude --model haiku\n",
    }
    calls: list[list[str]] = []

    def fake(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, outputs[argv[-1]], "")

    monkeypatch.setattr(agents.subprocess, "run", fake)
    processes = agents.read_processes()
    assert [argv[:3] for argv in calls] == [["ps", "-A", "-ww"]] * 2
    assert processes == [
        Process(1, 0, "/sbin/launchd", "/sbin/launchd"),
        Process(101, 100, "/Applications/My App.app/x", "claude --model haiku"),
    ]


def test_read_processes_without_ps(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("ps")

    monkeypatch.setattr(agents.subprocess, "run", missing)
    assert agents.read_processes() == []
