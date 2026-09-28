import subprocess
from dataclasses import replace

import pytest

from tmux_manager import agents, tmux
from tmux_manager.agents import AgentState, Process
from tmux_manager.manifests import Detection
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


# -------------------------------------------------------------------- state

CLAUDE_TRUST = (
    "─" * 40 + "\n ❯ 1. Yes, I trust this folder\n   2. No, exit\n\n"
    " Enter to confirm · Esc to cancel\n"
)
TRANSCRIPT = "Showing detailed transcript · ctrl+o to toggle\n"


def agent_pane(
    pane_id: str = "%1", *, panes: int = 2, activity: int = 0, title: str = ""
) -> TmuxPane:
    return replace(
        pane(pane_id, 100, "2.1.281"),
        agent="claude",
        window_panes=panes,
        window_activity=activity,
        title=title,
    )


@pytest.mark.parametrize(
    ("detection", "active", "previous", "expected"),
    [
        (Detection("blocked", "prompt"), True, None, "blocked"),
        (Detection("working", "spinner"), False, None, "working"),
        (Detection("idle", "prompt_box"), True, None, "working"),
        (Detection("idle", "prompt_box"), False, "working", "idle"),
        (Detection(), False, None, "idle"),
        (Detection("unknown", "overlay", skip_state_update=True), False, "blocked", "blocked"),
        (Detection("unknown", "overlay", skip_state_update=True), True, None, "working"),
    ],
)
def test_resolve_state(
    detection: Detection, active: bool, previous: AgentState | None, expected: AgentState
) -> None:
    assert agents.resolve_state(detection, active, previous) == expected


def test_changing_pane_is_working_until_the_grace_period_ends() -> None:
    tracker = agents.AgentTracker(grace_seconds=3)
    p = agent_pane()
    assert tracker.observe(p, "a", now=1000).state == "idle"  # first look: unknown, idle
    status = tracker.observe(p, "ab", now=1001)
    assert (status.state, status.last_change) == ("working", 1001)
    assert tracker.observe(p, "ab", now=1003).state == "working"
    assert tracker.observe(p, "ab", now=1004.5).state == "idle"


def test_trailing_blanks_do_not_count_as_change() -> None:
    tracker = agents.AgentTracker(grace_seconds=3)
    p = agent_pane()
    tracker.observe(p, "prompt\n\n\n", now=1000)
    assert tracker.observe(p, "prompt   \n", now=1001).state == "idle"


def test_single_pane_window_uses_window_activity() -> None:
    tracker = agents.AgentTracker(grace_seconds=3)
    busy = agent_pane(panes=1, activity=999)
    status = tracker.observe(busy, "streaming", now=1000)
    assert (status.state, status.last_change) == ("working", 999)
    quiet = agent_pane("%2", panes=1, activity=900)
    status = tracker.observe(quiet, "done", now=1000)
    assert (status.state, status.last_change) == ("idle", 900)


def test_window_activity_of_a_shared_window_does_not_make_working() -> None:
    tracker = agents.AgentTracker(grace_seconds=3)
    status = tracker.observe(agent_pane(panes=2, activity=999), "static", now=1000)
    assert (status.state, status.last_change) == ("idle", 999)


def test_blocked_screen_wins_over_activity() -> None:
    tracker = agents.AgentTracker(grace_seconds=3)
    status = tracker.observe(agent_pane(panes=1, activity=1000), CLAUDE_TRUST, now=1000)
    assert (status.state, status.rule) == ("blocked", "live_blocked_form")


def test_skip_state_update_keeps_previous_state() -> None:
    tracker = agents.AgentTracker(grace_seconds=3)
    p = agent_pane()
    assert tracker.observe(p, CLAUDE_TRUST, now=1000).state == "blocked"
    assert tracker.observe(p, CLAUDE_TRUST + TRANSCRIPT, now=1010).state == "blocked"


def test_tracker_forgets_closed_panes() -> None:
    tracker = agents.AgentTracker(grace_seconds=3)
    tracker.observe(agent_pane("%1"), "a", now=1000)
    tracker.retain(["%2"])
    assert tracker.observe(agent_pane("%1"), "b", now=1001).state == "idle"


def test_collect_captures_only_agent_panes(monkeypatch: pytest.MonkeyPatch) -> None:
    panes = [pane("%1", 100, "2.1.281"), pane("%3", 300, "vim"), pane("%6", 600, "agy")]
    captured: list[str] = []

    def capture(pane_id: str, *, colors: bool = False) -> str:
        captured.append(pane_id)
        if pane_id == "%6":
            raise tmux.TmuxError("can't find pane: %6")
        return CLAUDE_TRUST

    monkeypatch.setattr(tmux, "list_panes", lambda: panes)
    monkeypatch.setattr(tmux, "capture_pane_by_id", capture)
    monkeypatch.setattr(agents, "read_processes", lambda: PROCESSES)
    statuses = agents.collect(agents.AgentTracker())
    assert captured == ["%1", "%6"]
    assert [(s.pane.pane_id, s.agent, s.state) for s in statuses] == [("%1", "claude", "blocked")]


def test_sample_looks_twice(monkeypatch: pytest.MonkeyPatch) -> None:
    screens = iter(["one", "two"])
    sleeps: list[float] = []
    monkeypatch.setattr(tmux, "list_panes", lambda: [pane("%1", 100)])
    monkeypatch.setattr(tmux, "capture_pane_by_id", lambda pane_id: next(screens))
    monkeypatch.setattr(agents, "read_processes", lambda: PROCESSES)
    monkeypatch.setattr(agents.time, "sleep", sleeps.append)
    statuses = agents.sample(grace_seconds=3)
    assert sleeps == [agents.SAMPLE_DELAY_SECONDS]
    assert [s.state for s in statuses] == ["working"]


def test_sample_without_agents_does_not_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tmux, "list_panes", lambda: [pane("%3", 300)])
    monkeypatch.setattr(agents, "read_processes", lambda: PROCESSES)
    monkeypatch.setattr(agents.time, "sleep", lambda s: pytest.fail("slept"))
    assert agents.sample(grace_seconds=3) == []


def status(state: AgentState, session: str = "work", window: int = 0) -> agents.AgentStatus:
    p = replace(agent_pane(), session=session, window_index=window)
    return agents.AgentStatus(p, state, 0)


def test_sort_statuses_blocked_first() -> None:
    statuses = [
        status("idle", "a"),
        status("working", "b"),
        status("blocked", "c", 2),
        status("blocked", "c", 1),
    ]
    ordered = agents.sort_statuses(statuses)
    assert [(s.state, s.pane.window_index) for s in ordered] == [
        ("blocked", 1),
        ("blocked", 2),
        ("working", 0),
        ("idle", 0),
    ]


def test_rollup() -> None:
    statuses = [status("working"), status("blocked"), status("working"), status("idle")]
    assert agents.rollup(statuses) == "🔴1 🟢2 ⚪1"
    assert agents.rollup(statuses, ascii=True) == "B1 W2 I1"
    assert agents.rollup([]) == ""
