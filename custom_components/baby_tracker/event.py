"""Event platform for Baby Tracker: one Activity event entity per baby."""
from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ACTIVITY_EVENT_TYPES, DOMAIN, activity_signal
from .entity import baby_device_info, baby_unique_id

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up an Activity event entity for each baby."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(BabyTrackerActivityEvent(coordinator, baby.name) for baby in coordinator.data.get("babies") or [])


class BabyTrackerActivityEvent(CoordinatorEntity, EventEntity):
    """
    Fires when a refresh finds something new for the baby: a feeding, diaper,
    the start or end of a sleep, a bath or a medicine. Its attributes carry
    the details (type, time, ...), so automations can trigger on the event
    type without polling.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "activity"
    _attr_event_types = ACTIVITY_EVENT_TYPES

    def __init__(self, coordinator, baby_name):
        super().__init__(coordinator)
        self._baby_name = baby_name
        self._attr_unique_id = baby_unique_id(coordinator, baby_name, "activity")
        self._attr_device_info = baby_device_info(coordinator, baby_name)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(async_dispatcher_connect(
            self.hass, activity_signal(self.coordinator.config_entry.entry_id), self._handle_activity))

    @callback
    def _handle_activity(self, baby_name, activity, details) -> None:
        if baby_name != self._baby_name:
            return
        self._trigger_event(activity, details)
        self.async_write_ha_state()
