"""Re-export helpers from pytest-homeassistant-custom-component.

This module exists so that existing tests can use:
    from tests.common import MockConfigEntry
"""

from pytest_homeassistant_custom_component.common import MockConfigEntry

__all__ = ["MockConfigEntry"]
