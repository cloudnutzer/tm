"""The herdr manifest engine port: loading, regions, rule semantics, agent screens."""

from pathlib import Path

import pytest

from tmux_manager import manifests
from tmux_manager.manifests import ManifestError, bundled_manifests, detect, parse_manifest

HERDR_AGENTS = {
    "agy", "amp", "claude", "cline", "codex", "copilot", "cursor", "devin", "droid", "gemini",
    "grok", "hermes", "kilo", "kimi", "kiro", "letta", "maki", "muse", "opencode", "pi",
    "qodercli", "qwen",
}  # fmt: skip


def test_all_bundled_manifests_load() -> None:
    loaded = bundled_manifests()
    assert set(loaded) == HERDR_AGENTS
    assert all(m.rules for m in loaded.values())
    assert all(m.min_engine_version <= manifests.ENGINE_VERSION for m in loaded.values())
    assert "claude-code" in loaded["claude"].aliases


def rules_manifest(rules: str) -> manifests.Manifest:
    return parse_manifest(f'id = "test"\n\n{rules}')


def test_rule_semantics_apply_gates_priority_and_line_regex() -> None:
    # herdr: rule_semantics_apply_gates_priority_and_line_regex
    manifest = rules_manifest(
        """
[[rules]]
id = "low_contains"
state = "idle"
priority = 1
contains = ["match"]

[[rules]]
id = "high_nested_gates"
state = "working"
priority = 10
contains = ["match"]
all = [
  { any = [{ regex = ["w[io]n"] }, { contains = ["fallback"] }] },
]
not = [
  { contains = ["blocked"] },
]

[[rules]]
id = "line_regex"
state = "blocked"
priority = 20
line_regex = ["^exact line$"]
"""
    )
    assert detect(manifest, "match win").rule == "high_nested_gates"
    assert detect(manifest, "match win blocked").rule == "low_contains"
    assert detect(manifest, "before\nexact line\nafter").state == "blocked"
    assert detect(manifest, "nothing").rule is None


def test_contains_is_case_insensitive_regex_is_not() -> None:
    manifest = rules_manifest(
        """
[[rules]]
id = "contains"
state = "blocked"
contains = ["Esc To Cancel"]

[[rules]]
id = "regex"
state = "working"
priority = 5
regex = ["Thinking"]
"""
    )
    assert detect(manifest, "ESC to cancel").rule == "contains"
    assert detect(manifest, "thinking").rule is None
    assert detect(manifest, "Thinking").rule == "regex"


def test_ties_go_to_the_first_rule() -> None:
    manifest = rules_manifest(
        """
[[rules]]
id = "first"
state = "idle"
contains = ["x"]

[[rules]]
id = "second"
state = "working"
contains = ["x"]
"""
    )
    assert detect(manifest, "x").rule == "first"


def test_skip_state_update_rule() -> None:
    manifest = rules_manifest(
        """
[[rules]]
id = "activity"
state = "working"
priority = 10
contains = ["activity-marker"]

[[rules]]
id = "overlay"
state = "unknown"
priority = 20
skip_state_update = true
contains = ["overlay-marker"]
"""
    )
    detection = detect(manifest, "activity-marker overlay-marker")
    assert (detection.state, detection.skip_state_update) == ("unknown", True)


def test_osc_title_region_uses_the_pane_title_and_progress_never_matches() -> None:
    manifest = rules_manifest(
        """
[[rules]]
id = "title"
state = "working"
region = "osc_title"
contains = ["marker"]

[[rules]]
id = "progress"
state = "blocked"
region = "osc_progress"
regex = ["^4;"]
"""
    )
    assert detect(manifest, "", title="marker").rule == "title"
    assert detect(manifest, "marker", title="").rule is None
    assert detect(manifest, "4;0", title="4;0").rule is None


@pytest.mark.parametrize(
    ("text", "error"),
    [
        ('id = "x"\nrules = []', "at least one rule"),
        ('id = "x"\nbogus = 1\n[[rules]]\nid = "r"\ncontains = ["a"]', "unknown field"),
        ('id = "x"\nmin_engine_version = 4\n[[rules]]\nid = "r"\ncontains = ["a"]', "engine 4"),
        ('id = "x"\n[[rules]]\nid = "r"\nregion = "middle"\ncontains = ["a"]', "invalid region"),
        ('id = "x"\n[[rules]]\nid = "r"\nregex = ["("]', "invalid regex"),
        ('id = "x"\n[[rules]]\nid = "r"\nnot = [{ contains = ["a"] }]', "positive matcher"),
        (
            'id = "x"\n[[rules]]\nid = "r"\nstate = "idle"\nskip_state_update = true\n'
            'contains = ["a"]',
            "skip_state_update",
        ),
    ],
)
def test_invalid_manifests_are_rejected(text: str, error: str) -> None:
    with pytest.raises(ManifestError, match=error):
        parse_manifest(text)


def test_rust_regex_escapes() -> None:
    assert manifests.rust_to_python_regex(r"^[\x{2800}-\x{28FF}] ") == r"^[\U00002800-\U000028FF] "
    assert manifests.rust_to_python_regex(r"[\u{fe0e}]") == r"[\U0000FE0E]"
    assert manifests.rust_to_python_regex(r"\\x{41}\s") == r"\\x{41}\s"
    pattern = manifests.compile_rust_regex(r"^[\x{2800}-\x{28FF}]\s+\p{Alphabetic}+ing\b.*\z")
    assert pattern.search("⠂ Thinking about it")
    assert not pattern.search("⠂ Thinking\n")


@pytest.mark.parametrize(
    ("screen", "spec", "expected"),
    [
        # herdr: screen_regions_extract_structure_without_classifying_agent_state
        ("old\n\nnew\n", "bottom_lines(2)", "\nnew\n"),
        ("before\n› input\nafter\n", "after_last_prompt_marker", "after\n"),
        ("before\n› input\nafter\n", "before_current_prompt_marker", "before\n"),
        ("before\n› input\nafter\n", "whole_recent_without_current_prompt_marker", ""),
        ("no marker\n", "whole_recent_without_current_prompt_marker", "no marker\n"),
        ("• old\n■ latest\n› input\n", "current_prompt_block_marker", "■ latest"),
        ("• old\n■ latest\n› input\n", "after_current_prompt_block_marker", "■ latest\n› input\n"),
        ("› old\n• new\n", "current_prompt_block_marker", ""),
        ("above\n\n───\nbody\n───\nfooter\n", "above_prompt_box", "above\n\n"),
        ("above\n\n───\nbody\n───\nfooter\n", "last_non_empty_above_prompt_box", "above"),
        ("above\n───\nbody\n───\nfooter\n", "prompt_box_body", "body\n"),
        ("above\n───\nbody\n───\nfooter\n", "after_last_horizontal_rule", "footer\n"),
        # further regions used by the bundled manifests
        ("a\n\nb\n\nc\n", "bottom_non_empty_lines(2)", "b\n\nc\n"),
        ("\na\n\nb\nc\n", "top_non_empty_lines(2)", "\na\n\nb\n"),
        ("a\n", "top_non_empty_lines(0)", ""),
        ("a\n", "whole_recent", "a\n"),
        ("─── title ───\nbody\n", "after_last_horizontal_rule", "body\n"),
        ("── title ──\nbody\n", "after_last_horizontal_rule", "── title ──\nbody\n"),
        ("a ─ b\nbody\n", "after_last_horizontal_rule", "a ─ b\nbody\n"),
    ],
)
def test_screen_regions(screen: str, spec: str, expected: str) -> None:
    assert manifests.region(screen, "", spec) == expected


# ------------------------------------------------------------ agent screens

RULE = "─" * 60

CLAUDE_IDLE = f"""\
╭───────────────────────────────────────────────╮
│ ✻ Welcome to Claude Code!                     │
╰───────────────────────────────────────────────╯

> say hi
⏺ Hi! How can I help you today?

{RULE}
❯ 
{RULE}
  ? for shortcuts
"""

CLAUDE_THINKING = f"""\
> write a haiku about tmux
✢ Wandering… (1s · thinking)

{RULE}
❯ 
{RULE}
  ⏵⏵ accept edits on (shift+tab to cycle)
"""

CLAUDE_TRUST = f"""\
{RULE}
 Accessing workspace:

 /private/tmp/tma1-e2e

 Quick safety check: Is this a project you created or one you trust? (Like your
 own code, a well-known open source project, or work from your team). If not,
 take a moment to review what's in this folder first.

 Claude Code'll be able to read, edit, and execute files here.

 Security guide

 ❯ 1. Yes, I trust this folder
   2. No, exit

 Enter to confirm · Esc to cancel
"""

CLAUDE_BASH_PERMISSION = f"""\
⏺ Bash(rm -rf build)
  ⎿  Running…

{RULE}
 Bash command

   rm -rf build
   Remove the build directory

 Do you want to proceed?
 ❯ 1. Yes
   2. Yes, and don't ask again for rm commands in /tmp/project
   3. No, and tell Claude what to do differently (esc)

 Esc to cancel · Tab to amend · ctrl+e to explain
"""

CODEX_TRUST = """\
> You are in /tmp/project

  Do you trust the contents of this directory? Working with untrusted contents
  comes with higher risk of prompt injection.

› 1. Yes, continue
  2. No, quit

  Press enter to continue
"""

CODEX_WORKING = """\
• I'll look at the recent commits first.

• Working (5s • esc to interrupt)


› Summarize recent commits

  100% context left
"""

CODEX_IDLE = """\
• The last three commits touch the session list only.

› Ask Codex to do anything

  100% context left
"""

OPENCODE_PERMISSION = """\
  △ Permission required
  $ rm -rf build

  Allow once   Allow always   Reject
  ⇆ select  enter confirm
"""

OPENCODE_WORKING = """\
  Build  claude-sonnet
  ■■■■⬝⬝⬝⬝  esc interrupt
"""

AGY_WORKING = """\
⠋ Thinking (3s)
"""


@pytest.mark.parametrize(
    ("agent", "screen", "title", "state", "rule"),
    [
        ("claude", CLAUDE_IDLE, "✳ Claude Code", "idle", "live_prompt_box"),
        ("claude", CLAUDE_THINKING, "✳ Haiku about tmux", "working", "live_turn_working"),
        ("claude", CLAUDE_TRUST, "✳ Claude Code", "blocked", "live_blocked_form"),
        ("claude", CLAUDE_BASH_PERMISSION, "", "blocked", "bash_permission_prompt"),
        ("claude", "", "⠂ Refactoring the parser", "working", "osc_title_working"),
        ("codex", CODEX_TRUST, "", "blocked", "trust_directory"),
        ("codex", CODEX_WORKING, "", "working", "screen_working_fallback"),
        ("codex", CODEX_IDLE, "", None, None),
        ("codex", "", "Action Required: codex", "blocked", "osc_title_blocked"),
        ("opencode", OPENCODE_PERMISSION, "", "blocked", "permission_required"),
        ("opencode", OPENCODE_WORKING, "", "working", "progress_bar_working"),
        ("agy", AGY_WORKING, "", "working", "spinner_working"),
    ],
)
def test_agent_screens(
    agent: str, screen: str, title: str, state: str | None, rule: str | None
) -> None:
    detection = detect(bundled_manifests()[agent], screen, title)
    assert (detection.state, detection.rule) == (state, rule)


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize(
    ("fixture", "state", "rule"),
    [
        # captured live from Claude Code 2.1.283 in tmux 3.7c
        ("claude-2.1.283-trust.txt", "blocked", "live_blocked_form"),
        ("claude-2.1.283-bash-permission.txt", "blocked", "bash_permission_prompt"),
        ("claude-2.1.283-idle.txt", "idle", "live_prompt_box"),
        # while it streams an answer Claude shows no spinner: the screen looks
        # idle and only the activity signal can tell (see test_agents)
        ("claude-2.1.283-streaming.txt", "idle", "live_prompt_box"),
    ],
)
def test_real_claude_screens(fixture: str, state: str, rule: str) -> None:
    screen = (FIXTURES / fixture).read_text(encoding="utf-8")
    detection = detect(bundled_manifests()["claude"], screen, "✳ Claude Code")
    assert (detection.state, detection.rule) == (state, rule)
