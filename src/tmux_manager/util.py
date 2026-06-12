from __future__ import annotations

import time
from pathlib import Path


def short_path(path: str) -> str:
    home = str(Path.home())
    if path == home:
        return "~"
    if path.startswith(home + "/"):
        return "~" + path[len(home):]
    return path


def relative_time(epoch: int, now: int | None = None) -> str:
    delta = max(0, (now if now is not None else int(time.time())) - epoch)
    if delta < 60:
        return "now"
    if delta < 3600:
        return f"{delta // 60}m"
    if delta < 86400:
        return f"{delta // 3600}h"
    return f"{delta // 86400}d"
