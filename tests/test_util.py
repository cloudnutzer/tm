from pathlib import Path

from tmux_manager.util import relative_time, short_path


def test_relative_time_buckets() -> None:
    now = 1_750_000_000
    assert relative_time(now, now) == "now"
    assert relative_time(now - 59, now) == "now"
    assert relative_time(now - 60, now) == "1m"
    assert relative_time(now - 3599, now) == "59m"
    assert relative_time(now - 3600, now) == "1h"
    assert relative_time(now - 86400 * 3, now) == "3d"


def test_relative_time_never_negative() -> None:
    assert relative_time(2_000_000_000, 1_750_000_000) == "now"


def test_short_path_replaces_home() -> None:
    home = str(Path.home())
    assert short_path(home) == "~"
    assert short_path(f"{home}/src/x") == "~/src/x"
    assert short_path(f"{home}2/x") == f"{home}2/x"
    assert short_path("/tmp") == "/tmp"
