from __future__ import annotations

from rich.text import Text
from textual.widgets import Input


class FilterInput(Input):
    """An Input that leaves ``?`` to the screen so help opens while typing.

    Textual drops screen bindings for every key a focused Input would consume,
    even priority ones; declining ``?`` here lets the screen's help binding win.
    """

    def check_consume_key(self, key: str, character: str | None) -> bool:
        if key == "question_mark":
            return False
        return super().check_consume_key(key, character)


def tail_of_pane(content: str, height: int) -> Text:
    """The last ``height`` non-blank lines of a captured pane, colors intact.

    capture-pane returns the full pane height including the blank rows below
    the prompt; showing the top would hide the most recent output.
    """
    lines: list[Text] = list(Text.from_ansi(content).split("\n"))
    for line in lines:
        line.rstrip()
    while lines and not lines[-1].plain.strip():
        lines.pop()
    if height > 0:
        lines = lines[-height:]
    return Text("\n").join(lines)
