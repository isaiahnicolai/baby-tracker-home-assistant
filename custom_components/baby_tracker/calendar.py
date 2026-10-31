"""Calendar platform for Baby Tracker: what happened for each baby, as calendar events."""
from datetime import datetime

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .entity import baby_device_info, baby_unique_id

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up a calendar for each baby."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(BabyTrackerCalendar(coordinator, baby.name) for baby in coordinator.data.get("babies") or [])


def _calendar_event(event) -> CalendarEvent:
    return CalendarEvent(
        start=event["start"],
        end=event["end"],
        summary=event["summary"],
        description=event.get("description") or None,
    )


class BabyTrackerCalendar(CoordinatorEntity, CalendarEntity):
    """
    A baby's feeds, sleeps, baths, doctor visits and medicines. A sleep lasts
    as long as it did; everything else is a 15-minute event. The calendar's
    current event is the most recent thing that happened.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "activity_calendar"

    def __init__(self, coordinator, baby_name):
        super().__init__(coordinator)
        self._baby_name = baby_name
        self._attr_unique_id = baby_unique_id(coordinator, baby_name, "activity_calendar")
        self._attr_device_info = baby_device_info(coordinator, baby_name)

    @property
    def event(self) -> CalendarEvent | None:
        """The most recent event, from the last refresh."""
        baby_data = ((self.coordinator.data or {}).get("baby_data") or {}).get(self._baby_name) or {}
        latest = baby_data.get("last_event")
        return _calendar_event(latest) if latest else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Events between two times, read from the local database."""
        baby_id = self.coordinator.baby_id_for(self._baby_name)
        events = await hass.async_add_executor_job(
            self.coordinator.baby_tracker.get_events_between, baby_id, start_date, end_date)
        return [_calendar_event(event) for event in events]
