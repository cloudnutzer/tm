from __future__ import annotations

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
