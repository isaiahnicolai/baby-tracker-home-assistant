"""Home Assistant test setup. Skipped unless pytest-homeassistant-custom-component is installed."""
import pytest

pytest.importorskip("pytest_homeassistant_custom_component")


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield
