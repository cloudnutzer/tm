"""herdr's agent screen manifests and a Python port of its rule engine.

The TOML files in ``agent_manifests/`` come unchanged from herdr
(https://github.com/herdrdev/herdr, Apache-2.0, see NOTICE there). Each
manifest holds rules that look at a *region* of the captured pane text (or at
the pane title) and name a state. The matching rule with the highest priority
wins; ties go to the rule listed first. This mirrors ``src/detect/manifest.rs``:

- ``contains`` matches case-insensitively, ``regex`` and ``line_regex`` are
  case-sensitive unless the pattern says ``(?i)``; ``line_regex`` must match
  one line of the region.
- all matchers of a gate must match, nested ``all`` gates too, at least one
  ``any`` gate if there are any, and no ``not`` gate.
- ``osc_title`` is the pane title. ``osc_progress`` (OSC 9;4) is not
  available through tmux, so rules on it never match.

Patterns use Rust regex syntax; the third-party ``regex`` module understands
all of it that the manifests use except ``\\x{HEX}`` and ``\\u{HEX}``, which
are rewritten.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Any, Literal

import regex
from regex import Pattern

ENGINE_VERSION = 3
"""Highest ``min_engine_version`` this port implements (herdr's as of the vendored commit)."""

ManifestState = Literal["idle", "working", "blocked", "unknown"]
STATES: tuple[ManifestState, ...] = ("idle", "working", "blocked", "unknown")

_FIXED_REGIONS = frozenset(
    {
        "whole_recent",
        "after_last_prompt_marker",
        "before_current_prompt_marker",
        "whole_recent_without_current_prompt_marker",
        "current_prompt_block_marker",
        "after_current_prompt_block_marker",
        "prompt_box_body",
        "above_prompt_box",
        "last_non_empty_above_prompt_box",
        "after_last_horizontal_rule",
        "osc_title",
        "osc_progress",
    }
)
_RULE_KEYS = frozenset(
    {
        "id",
        "state",
        "priority",
        "region",
        "visible_idle",
        "visible_blocker",
        "visible_working",
        "skip_state_update",
        "all",
        "any",
        "not",
        "contains",
        "regex",
        "line_regex",
    }
)
_GATE_KEYS = frozenset({"all", "any", "not", "contains", "regex", "line_regex"})
_MANIFEST_KEYS = frozenset(
    {"id", "version", "min_engine_version", "updated_at", "aliases", "rules"}
)


class ManifestError(ValueError):
    """A manifest cannot be used."""


@dataclass(frozen=True)
class Gate:
    contains: tuple[str, ...] = ()
    """Lower-cased needles."""
    regex: tuple[Pattern[str], ...] = ()
    line_regex: tuple[Pattern[str], ...] = ()
    all: tuple[Gate, ...] = ()
    any: tuple[Gate, ...] = ()
    not_: tuple[Gate, ...] = ()


@dataclass(frozen=True)
class Rule:
    id: str
    state: ManifestState
    priority: int
    region: str
    skip_state_update: bool
    gate: Gate


@dataclass(frozen=True)
class Manifest:
    id: str
    aliases: tuple[str, ...]
    min_engine_version: int
    rules: tuple[Rule, ...]


@dataclass(frozen=True)
class Detection:
    """Result of evaluating a manifest; ``rule`` is None when nothing matched."""

    state: ManifestState | None = None
    rule: str | None = None
    skip_state_update: bool = False


# ------------------------------------------------------------------ loading


def parse_manifest(text: str) -> Manifest:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ManifestError(str(error)) from error
    _reject_unknown(data, _MANIFEST_KEYS, "manifest")
    manifest_id = data.get("id")
    if not isinstance(manifest_id, str) or not manifest_id:
        raise ManifestError("manifest needs an id")
    min_engine = data.get("min_engine_version", 1)
    if not isinstance(min_engine, int) or min_engine > ENGINE_VERSION:
        raise ManifestError(
            f"{manifest_id}: needs engine {min_engine}, this is engine {ENGINE_VERSION}"
        )
    raw_rules = data.get("rules", [])
    if not isinstance(raw_rules, list) or not raw_rules:
        raise ManifestError(f"{manifest_id}: manifest must contain at least one rule")
    rules = tuple(_parse_rule(raw, manifest_id) for raw in raw_rules)
    return Manifest(
        id=manifest_id,
        aliases=tuple(_strings(data, "aliases", manifest_id)),
        min_engine_version=min_engine,
        rules=rules,
    )


def _parse_rule(raw: Any, manifest_id: str) -> Rule:
    if not isinstance(raw, dict):
        raise ManifestError(f"{manifest_id}: rules must be tables")
    rule_id = raw.get("id")
    if not isinstance(rule_id, str) or not rule_id.strip():
        raise ManifestError(f"{manifest_id}: rule id must not be empty")
    context = f"{manifest_id}.{rule_id}"
    _reject_unknown(raw, _RULE_KEYS, context)
    state = raw.get("state", "unknown")
    if state not in STATES:
        raise ManifestError(f"{context}: unknown state {state!r}")
    priority = raw.get("priority", 0)
    if not isinstance(priority, int):
        raise ManifestError(f"{context}: priority must be an integer")
    region = raw.get("region", "whole_recent")
    if not isinstance(region, str) or not valid_region(region):
        raise ManifestError(f"{context}: invalid region {region!r}")
    skip = raw.get("skip_state_update", False)
    if skip and state != "unknown":
        raise ManifestError(f"{context}: skip_state_update needs state = 'unknown'")
    gate = _parse_gate(raw, context)
    if not _has_positive_matcher(gate):
        raise ManifestError(f"{context}: rule must contain a positive matcher")
    return Rule(
        id=rule_id,
        state=state,
        priority=priority,
        region=region.strip(),
        skip_state_update=bool(skip),
        gate=gate,
    )


def _parse_gate(raw: Mapping[str, Any], context: str) -> Gate:
    def nested(key: str) -> tuple[Gate, ...]:
        value = raw.get(key, [])
        if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
            raise ManifestError(f"{context}: {key} must be a list of tables")
        for item in value:
            _reject_unknown(item, _GATE_KEYS, context)
        return tuple(_parse_gate(item, context) for item in value)

    return Gate(
        contains=tuple(needle.lower() for needle in _strings(raw, "contains", context)),
        regex=tuple(compile_rust_regex(p, context) for p in _strings(raw, "regex", context)),
        line_regex=tuple(
            compile_rust_regex(p, context) for p in _strings(raw, "line_regex", context)
        ),
        all=nested("all"),
        any=nested("any"),
        not_=nested("not"),
    )


def _has_positive_matcher(gate: Gate) -> bool:
    return bool(gate.contains or gate.regex or gate.line_regex or gate.all or gate.any)


def _strings(raw: Mapping[str, Any], key: str, context: str) -> list[str]:
    value = raw.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ManifestError(f"{context}: {key} must be a list of strings")
    return value


def _reject_unknown(raw: Mapping[str, Any], allowed: frozenset[str], context: str) -> None:
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ManifestError(f"{context}: unknown field {unknown[0]!r}")


def compile_rust_regex(pattern: str, context: str = "pattern") -> Pattern[str]:
    try:
        return regex.compile(rust_to_python_regex(pattern))
    except regex.error as error:
        raise ManifestError(f"{context}: invalid regex {pattern!r}: {error}") from error


def rust_to_python_regex(pattern: str) -> str:
    """Rewrite Rust's ``\\x{HEX}``/``\\u{HEX}`` escapes as ``\\UXXXXXXXX``; leave the rest."""
    out: list[str] = []
    i = 0
    while i < len(pattern):
        char = pattern[i]
        if char != "\\" or i + 1 >= len(pattern):
            out.append(char)
            i += 1
            continue
        if pattern[i + 1] in "xuU" and pattern.startswith("{", i + 2):
            end = pattern.find("}", i + 3)
            if end != -1:
                try:
                    out.append(f"\\U{int(pattern[i + 3 : end], 16):08X}")
                    i = end + 1
                    continue
                except ValueError:
                    pass
        out.append(pattern[i : i + 2])  # any other escape, including "\\\\"
        i += 2
    return "".join(out)


@cache
def bundled_manifests() -> dict[str, Manifest]:
    """The vendored manifests by agent id; loaded and compiled once."""
    manifests = {}
    folder = resources.files("tmux_manager") / "agent_manifests"
    for entry in sorted(folder.iterdir(), key=lambda e: e.name):
        if entry.name.endswith(".toml"):
            manifest = parse_manifest(entry.read_text(encoding="utf-8"))
            manifests[manifest.id] = manifest
    return manifests


# --------------------------------------------------------------- evaluation


def detect(manifest: Manifest, screen: str, title: str = "") -> Detection:
    """Evaluate a manifest against a pane's text and title."""
    best: Rule | None = None
    for rule in manifest.rules:
        if best is not None and best.priority >= rule.priority:
            continue  # cannot win: ties go to the earlier rule
        text = region(screen, title, rule.region)
        if gate_matches(rule.gate, text, text.lower()):
            best = rule
    if best is None:
        return Detection()
    return Detection(state=best.state, rule=best.id, skip_state_update=best.skip_state_update)


def gate_matches(gate: Gate, text: str, lower: str) -> bool:
    if not all(needle in lower for needle in gate.contains):
        return False
    if not all(pattern.search(text) for pattern in gate.regex):
        return False
    if gate.line_regex:
        lines = _lines(text)
        if not all(any(p.search(line) for line in lines) for p in gate.line_regex):
            return False
    if not all(gate_matches(nested, text, lower) for nested in gate.all):
        return False
    if gate.any and not any(gate_matches(nested, text, lower) for nested in gate.any):
        return False
    return not any(gate_matches(nested, text, lower) for nested in gate.not_)


# ------------------------------------------------------------------ regions


def valid_region(spec: str) -> bool:
    spec = spec.strip()
    return (
        spec in _FIXED_REGIONS
        or _region_count(spec, "bottom_lines") is not None
        or _region_count(spec, "bottom_non_empty_lines") is not None
        or _top_region_count(spec) is not None
    )


def region(screen: str, title: str, spec: str) -> str:
    spec = spec.strip()
    if spec == "osc_title":
        return title
    if spec == "osc_progress":
        return ""  # OSC 9;4 progress is not exposed by tmux
    content = screen
    match spec:
        case "whole_recent":
            return content
        case "after_last_prompt_marker":
            return _after_last_prompt_marker(content)
        case "before_current_prompt_marker":
            return _before_current_prompt_marker(content)
        case "whole_recent_without_current_prompt_marker":
            return "" if _current_codex_prompt_index(_lines(content)) is not None else content
        case "current_prompt_block_marker":
            return _current_prompt_block_marker(content)
        case "after_current_prompt_block_marker":
            return _after_current_prompt_block_marker(content)
        case "prompt_box_body":
            return _prompt_box_body(content)
        case "above_prompt_box":
            return _above_prompt_box(content)
        case "last_non_empty_above_prompt_box":
            return _last_non_empty_line(_above_prompt_box(content))
        case "after_last_horizontal_rule":
            return _after_last_horizontal_rule(content)
    count = _region_count(spec, "bottom_lines")
    if count is not None:
        lines = _lines(content)
        return _slice_from_line(content, lines, max(0, len(lines) - count))
    count = _region_count(spec, "bottom_non_empty_lines")
    if count is not None:
        return _bottom_non_empty_lines(content, count)
    count = _top_region_count(spec)
    if count is not None:
        return _top_non_empty_lines(content, count)
    return ""


def _region_count(spec: str, name: str) -> int | None:
    if not (spec.startswith(name + "(") and spec.endswith(")")):
        return None
    count = spec[len(name) + 1 : -1]
    return int(count) if count.isascii() and count.isdigit() else None


def _top_region_count(spec: str) -> int | None:
    count = _region_count(spec, "top_non_empty_lines")
    if count is None or spec[len("top_non_empty_lines(")] == "0" or count > 0xFFFF:
        return None
    return count


def _lines(content: str) -> list[str]:
    """Like Rust's ``str::lines``: no empty last line, a trailing CR is dropped."""
    if not content:
        return []
    lines = content.split("\n")
    if lines[-1] == "":
        lines.pop()
    return [line[:-1] if line.endswith("\r") else line for line in lines]


def _line_start(content: str, lines: Sequence[str], index: int) -> int:
    return min(sum(len(line) + 1 for line in lines[:index]), len(content))


def _slice_from_line(content: str, lines: Sequence[str], index: int) -> str:
    return content[_line_start(content, lines, index) :]


def _non_empty_indexes(lines: Sequence[str]) -> list[int]:
    return [index for index, line in enumerate(lines) if line.strip()]


def _bottom_non_empty_lines(content: str, count: int) -> str:
    lines = _lines(content)
    indexes = _non_empty_indexes(lines)[-count:] if count else []
    return _slice_from_line(content, lines, indexes[0]) if indexes else ""


def _top_non_empty_lines(content: str, count: int) -> str:
    lines = _lines(content)
    indexes = _non_empty_indexes(lines)[:count]
    return content[: _line_start(content, lines, indexes[-1] + 1)] if indexes else ""


def _codex_prompt_line(line: str) -> bool:
    return line == "›" or line.startswith("› ")


def _codex_block_marker_line(line: str) -> bool:
    return line.startswith(("•", "■", "✗", "✓"))


def _last_index(lines: Sequence[str], predicate: Any) -> int | None:
    for index in range(len(lines) - 1, -1, -1):
        if predicate(lines[index]):
            return index
    return None


def _current_codex_prompt_index(lines: Sequence[str]) -> int | None:
    index = _last_index(lines, _codex_prompt_line)
    if index is None or any(_codex_block_marker_line(line) for line in lines[index + 1 :]):
        return None
    return index


def _after_last_prompt_marker(content: str) -> str:
    lines = _lines(content)
    index = _last_index(lines, _codex_prompt_line)
    return content if index is None else _slice_from_line(content, lines, index + 1)


def _before_current_prompt_marker(content: str) -> str:
    lines = _lines(content)
    index = _current_codex_prompt_index(lines)
    return content if index is None else content[: _line_start(content, lines, index)]


def _current_prompt_block_marker(content: str) -> str:
    lines = _lines(content)
    prompt = _current_codex_prompt_index(lines)
    if prompt is None:
        return ""
    block = _last_index(lines[:prompt], _codex_block_marker_line)
    return "" if block is None else lines[block]


def _after_current_prompt_block_marker(content: str) -> str:
    lines = _lines(content)
    prompt = _current_codex_prompt_index(lines)
    if prompt is None:
        return ""
    block = _last_index(lines[:prompt], _codex_block_marker_line)
    return "" if block is None else _slice_from_line(content, lines, block)


def _is_horizontal_rule(line: str) -> bool:
    trimmed = line.strip()
    rule_chars = len(trimmed) - len(trimmed.lstrip("─"))
    if rule_chars == 0:
        return False
    suffix = trimmed[rule_chars:].lstrip()
    return not suffix or rule_chars >= 3


def _prompt_box_top(lines: Sequence[str]) -> int | None:
    borders = 0
    for index in range(len(lines) - 1, -1, -1):
        if _is_horizontal_rule(lines[index]):
            borders += 1
            if borders == 2:
                return index
    return None


def _prompt_box_body(content: str) -> str:
    lines = _lines(content)
    top = _prompt_box_top(lines)
    if top is None:
        return ""
    end = next(
        (index for index in range(top + 1, len(lines)) if _is_horizontal_rule(lines[index])),
        len(lines),
    )
    return content[_line_start(content, lines, top + 1) : _line_start(content, lines, end)]


def _above_prompt_box(content: str) -> str:
    lines = _lines(content)
    top = _prompt_box_top(lines)
    return content if top is None else content[: _line_start(content, lines, top)]


def _after_last_horizontal_rule(content: str) -> str:
    last_rule_end = 0
    offset = 0
    for line in _lines(content):
        next_offset = offset + len(line) + 1
        if _is_horizontal_rule(line):
            last_rule_end = min(next_offset, len(content))
        offset = next_offset
    return content[last_rule_end:]


def _last_non_empty_line(content: str) -> str:
    return next((line for line in reversed(_lines(content)) if line.strip()), "")
