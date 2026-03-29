"""Configure test environment for yamaha_musiccast integration tests.

The aiomusiccast library is bundled inside the custom component at
custom_components/yamaha_musiccast/aiomusiccast/. This conftest injects it
into sys.modules as the top-level 'aiomusiccast' package so test files can
import it the same way the integration itself does.
"""

from __future__ import annotations

import importlib.util
import os
import sys

import pytest
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Inject aiomusiccast as a top-level package before any test file is loaded.
# ---------------------------------------------------------------------------
_ROOT = os.path.dirname(os.path.dirname(__file__))
_AIO_PATH = os.path.join(_ROOT, "custom_components", "yamaha_musiccast", "aiomusiccast")

if "aiomusiccast" not in sys.modules:
    _spec = importlib.util.spec_from_file_location(
        "aiomusiccast",
        os.path.join(_AIO_PATH, "__init__.py"),
        submodule_search_locations=[_AIO_PATH],
    )
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules["aiomusiccast"] = _mod
    _spec.loader.exec_module(_mod)

# Make the project root importable so custom_components.yamaha_musiccast.*
# can be used without installing the package.
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

from custom_components.yamaha_musiccast.aiomusiccast.musiccast_data import Category  # noqa: E402


@pytest.fixture
def mock_coordinator():
    """Minimal mock coordinator with a single 'main' zone."""
    coord = MagicMock()
    coord.data.device_id = "TEST_DEVICE_ID"
    coord.data.mac_addresses = {"wired": "aa:bb:cc:dd:ee:ff"}
    coord.data.model_name = "RX-A3080"
    coord.data.system_version = "2.50"
    coord.data.category = Category.AV_RECEIVER
    coord.selected_scenes = {}

    main_zone = MagicMock()
    main_zone.name = "Main"
    main_zone.capabilities = []
    main_zone.min_volume = 0
    main_zone.max_volume = 161

    coord.data.zones = {"main": main_zone}
    coord.data.capabilities = []

    return coord
