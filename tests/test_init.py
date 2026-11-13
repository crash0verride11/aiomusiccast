"""Tests for the package surface."""

import pytest

import aiomusiccast_co
from aiomusiccast_co import __main__


def test_public_api() -> None:
    for name in aiomusiccast_co.__all__:
        assert hasattr(aiomusiccast_co, name)


def test_version_is_set() -> None:
    assert isinstance(aiomusiccast_co.__version__, str)
    assert aiomusiccast_co.__version__.count(".") == 2


def test_module_entry_point_exits() -> None:
    with pytest.raises(SystemExit, match="does not expose a CLI"):
        __main__.main()
