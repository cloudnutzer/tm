import pytest

from tmux_manager import __version__
from tmux_manager.cli import build_parser


def test_version_flag_prints_version(capsys):
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_help_flag_lists_key_bindings(capsys):
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "sessionizer" in out
    assert "attach" in out


def test_unknown_argument_fails():
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["--bogus"])
    assert exc.value.code != 0
