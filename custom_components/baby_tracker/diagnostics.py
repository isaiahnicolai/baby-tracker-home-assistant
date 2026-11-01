"""Diagnostics for Baby Tracker: what to attach to a bug report, with credentials removed."""
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_DEVICE_UUID, CONF_EMAIL, CONF_PASSWORD, DOMAIN

TO_REDACT = {CONF_EMAIL, CONF_PASSWORD, CONF_DEVICE_UUID, "account_id"}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    data = (coordinator.data if coordinator else None) or {}
    babies = data.get("babies") or []
    baby_data = data.get("baby_data") or {}

    return {
        "entry": {
            "version": entry.version,
            "minor_version": entry.minor_version,
            "data": async_redact_data(entry.data, TO_REDACT),
            "options": async_redact_data(entry.options, TO_REDACT),
        },
        "last_update_success": coordinator.last_update_success if coordinator else None,
        "last_sync": coordinator.last_sync_result if coordinator else None,
        "pending_uploads": coordinator.pending_uploads if coordinator else None,
        "babies": [{"id": baby.object_id, "name": baby.name, "dob": baby.dob} for baby in babies],
        "insights": {baby.object_id: (baby_data.get(baby.name) or {}).get("insights") for baby in babies},
    }
