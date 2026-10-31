"""Shared entity identity for Baby Tracker: unique IDs and devices keyed by baby ID."""
import logging
from datetime import timedelta

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import CLOCK_TICK_SECONDS, DOMAIN, VERSION

_LOGGER = logging.getLogger(__name__)


class ClockTickMixin:
    """
    For entities whose state depends on the time of day, not only on the
    coordinator's data (a prediction coming due, night falling, hours since a
    feed). Re-evaluates every minute instead of waiting for the next refresh.
    Put it first in the base classes.
    """

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_time_interval(self.hass, self._async_clock_tick, timedelta(seconds=CLOCK_TICK_SECONDS)))

    @callback
    def _async_clock_tick(self, now):
        self.async_write_ha_state()


def hours_since_feeding(coordinator, time_data):
    """
    Hours since the last feeding as of now. The client works the figure out
    when the data is fetched, so the time since then is added to keep it
    current between refreshes. None when there is no feeding.
    """
    hours = (time_data or {}).get("hours_since_last_feeding")
    if hours is None:
        return None
    fetched_at = getattr(coordinator, "fetched_at", None)
    if fetched_at is not None:
        hours += max(0.0, (dt_util.utcnow() - fetched_at).total_seconds() / 3600)
    return hours


def baby_unique_id(coordinator, baby_name, suffix):
    """
    Unique ID for a baby's entity. Uses the baby's ID, not its name, so
    renaming a baby in the app keeps its entities.
    """
    return f"{DOMAIN}_{coordinator.email}_{coordinator.baby_id_for(baby_name)}_{suffix}"


def baby_device_info(coordinator, baby_name):
    return DeviceInfo(
        identifiers={(DOMAIN, f"{coordinator.email}_{coordinator.baby_id_for(baby_name)}")},
        name=baby_name,
        manufacturer="Baby Tracker",
        model="API Integration",
        sw_version=VERSION,
    )


def system_device_info(coordinator):
    return DeviceInfo(
        identifiers={(DOMAIN, f"{coordinator.email}_system")},
        name="Baby Tracker",
        manufacturer="Baby Tracker",
        model="API Integration",
        sw_version=VERSION,
    )


def _find_device(dev_reg, entry_id, identifier):
    """Look up this entry's device by identifier on any supported Home Assistant version."""
    if hasattr(dev_reg, "async_get_device_by_identifier"):  # 2026.x: identifiers are unique per entry
        return dev_reg.async_get_device_by_identifier(identifier, entry_id)
    return dev_reg.async_get_device(identifiers={identifier})


def _legacy_key(name):
    return name.lower().replace(" ", "_")


# Sensors that were merged into others; their registry entries would otherwise stay behind as orphans
RETIRED_SENSOR_SUFFIXES = ("_bottle_oz",)  # the oz half of Bottle Volume (the ml half kept its ID)


def remove_retired_entities(hass, entry):
    """Delete the registry entries of sensors that no longer exist. Safe to run repeatedly."""
    from homeassistant.helpers import entity_registry as er

    ent_reg = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        if entity.domain == "sensor" and entity.unique_id.endswith(RETIRED_SENSOR_SUFFIXES):
            _LOGGER.info(f"Removing {entity.entity_id}, which was merged into another sensor")
            ent_reg.async_remove(entity.entity_id)


def migrate_to_baby_ids(hass, entry, email, babies):
    """
    Re-key entities and devices created when IDs were based on the baby's
    name ("{email}_{name}") to use the baby's ID instead. Entity IDs,
    history and dashboards are unchanged. Safe to run repeatedly.
    """
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    # Longest names first, so "ann_marie" isn't mistaken for "ann"
    keys = sorted(((_legacy_key(b.name), b.object_id) for b in babies if b.name),
                  key=lambda kv: len(kv[0]), reverse=True)
    if not keys:
        return

    ent_reg = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        for legacy, baby_id in keys:
            prefix = f"{DOMAIN}_{email}_{legacy}_"
            if entity.unique_id.startswith(prefix):
                new_unique_id = f"{DOMAIN}_{email}_{baby_id}_" + entity.unique_id[len(prefix):]
                if ent_reg.async_get_entity_id(entity.domain, entity.platform, new_unique_id):
                    _LOGGER.warning(f"Not migrating {entity.entity_id}: {new_unique_id} already exists")
                else:
                    ent_reg.async_update_entity(entity.entity_id, new_unique_id=new_unique_id)
                    _LOGGER.info(f"Migrated {entity.entity_id} to unique ID {new_unique_id}")
                break

    dev_reg = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(dev_reg, entry.entry_id):
        for legacy, baby_id in keys:
            old = (DOMAIN, f"{email}_{legacy}")
            if old in device.identifiers:
                new = (DOMAIN, f"{email}_{baby_id}")
                if _find_device(dev_reg, entry.entry_id, new):
                    _LOGGER.warning(f"Not migrating device {device.name}: {new[1]} already exists")
                else:
                    dev_reg.async_update_device(device.id, new_identifiers=(device.identifiers - {old}) | {new})
                break
