"""Button platform for Baby Tracker."""
import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import BOTTLE_TYPE_PUMPED, DOMAIN, UNIT_SYSTEM_IMPERIAL
from .entity import baby_device_info, baby_unique_id, system_device_info

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Baby Tracker buttons based on a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]

    buttons = []

    # Get list of all babies
    babies = coordinator.data.get("babies", [])

    if not babies:
        # Fallback to single baby mode
        baby_info = coordinator.data.get("baby_info")
        if baby_info:
            babies = [baby_info]

    # Create quick action buttons for each baby
    for baby in babies:
        if not baby:
            continue
        baby_name = baby.name if hasattr(baby, 'name') else "Baby"

        # Add bottle size buttons for this baby
        buttons.extend([
            # Log a bottle / medicine from the baby's Bottle Size, Bottle Type, Medicine and Medicine Amount controls
            BabyTrackerAddBottleButton(coordinator, baby_name),
            BabyTrackerGiveMedicineButton(coordinator, baby_name),
            # Nursing timer
            BabyTrackerNursingButton(coordinator, baby_name, "start_nursing_left", side="left"),
            BabyTrackerNursingButton(coordinator, baby_name, "start_nursing_right", side="right"),
            BabyTrackerNursingButton(coordinator, baby_name, "end_nursing", side=None),
            BabyTrackerTummyTimeButton(coordinator, baby_name),
            # Fixed-size bottles and Tylenol, from before the controls above
            BabyTrackerBottleButton(coordinator, baby_name, "3oz", 3),
            BabyTrackerBottleButton(coordinator, baby_name, "4oz", 4),
            BabyTrackerBottleButton(coordinator, baby_name, "5oz", 5),
            BabyTrackerBottleButton(coordinator, baby_name, "6oz", 6),
            BabyTrackerBottleButton(coordinator, baby_name, "7oz", 7),
            BabyTrackerBottleButton(coordinator, baby_name, "8oz", 8),
            # Diaper buttons
            BabyTrackerDiaperButton(coordinator, baby_name, "Wet", pee=True, poo=False),
            BabyTrackerDiaperButton(coordinator, baby_name, "Dirty", pee=False, poo=True),
            BabyTrackerDiaperButton(coordinator, baby_name, "Mixed", pee=True, poo=True),
            # Bath buttons (just one general bath button with 10 min default)
            BabyTrackerBathButton(coordinator, baby_name, "Bath"),
            # Sleep buttons
            BabyTrackerSleepButton(coordinator, baby_name, "Start Sleep", is_start=True),
            BabyTrackerSleepButton(coordinator, baby_name, "End Sleep", is_start=False),
            # Medicine buttons
            BabyTrackerMedicineButton(coordinator, baby_name, "Tylenol", 3.75),
        ])

    # Add global buttons (not per-baby, affects entire integration)
    buttons.append(BabyTrackerSyncButton(coordinator))
    buttons.append(BabyTrackerForceResyncButton(coordinator))

    async_add_entities(buttons)


class BabyTrackerButton(CoordinatorEntity, ButtonEntity):
    """
    Base for the buttons. A second press of the same button within a few seconds is
    ignored, so a double tap doesn't log a record twice. A subclass does its work in _press.
    """

    async def async_press(self) -> None:
        """Handle button press."""
        if self.coordinator.is_repeat_press(self.unique_id):
            return
        try:
            await self._press()
        except BaseException:
            # A press that failed isn't debounced: the user can try again at once
            self.coordinator.finish_press(self.unique_id, succeeded=False)
            raise
        self.coordinator.finish_press(self.unique_id, succeeded=True)

    async def _press(self) -> None:
        raise NotImplementedError


class BabyTrackerAddBottleButton(BabyTrackerButton):
    """Button to log a bottle of the baby's Bottle Size, as formula or pumped milk (Bottle Type)."""

    def __init__(self, coordinator, baby_name):
        """Initialize the button."""
        super().__init__(coordinator)
        self._baby_name = baby_name
        self._baby_id = coordinator.baby_id_for(baby_name)

        self._attr_has_entity_name = True
        self._attr_translation_key = "add_selected_bottle"
        self._attr_unique_id = baby_unique_id(coordinator, baby_name, "add_bottle")
        self._attr_device_info = baby_device_info(coordinator, baby_name)

    async def _press(self) -> None:
        coordinator = self.coordinator
        amount = coordinator.control(self._baby_id, "bottle_size")
        is_pumped = coordinator.control(self._baby_id, "bottle_type") == BOTTLE_TYPE_PUMPED
        _LOGGER.info(f"Adding {amount} {'pumped' if is_pumped else 'formula'} bottle for {self._baby_name}")

        await self.hass.services.async_call(
            DOMAIN,
            "add_pumped" if is_pumped else "add_formula",
            {
                "baby_name": self._baby_name,
                "amount": amount,
                # The Bottle Size number is in oz for an imperial entry and mL for a metric one
                "is_english_measure": coordinator.unit_system == UNIT_SYSTEM_IMPERIAL,
                "note": "Added from Home Assistant"
            },
            blocking=True
        )


class BabyTrackerGiveMedicineButton(BabyTrackerButton):
    """Button to log a dose of the baby's selected Medicine, in the Medicine Amount."""

    def __init__(self, coordinator, baby_name):
        """Initialize the button."""
        super().__init__(coordinator)
        self._baby_name = baby_name
        self._baby_id = coordinator.baby_id_for(baby_name)

        self._attr_has_entity_name = True
        self._attr_translation_key = "give_selected_medicine"
        self._attr_unique_id = baby_unique_id(coordinator, baby_name, "give_medicine")
        self._attr_device_info = baby_device_info(coordinator, baby_name)

    async def _press(self) -> None:
        medicine = self.coordinator.selected_medicine(self._baby_id)
        if not medicine:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_medicine_selected")
        amount = self.coordinator.control(self._baby_id, "medicine_amount")
        _LOGGER.info(f"Giving {medicine} ({amount}) to {self._baby_name}")

        await self.hass.services.async_call(
            DOMAIN,
            "log_medicine",
            {
                "baby_name": self._baby_name,
                "medicine_name": medicine,
                "amount": amount,
                "note": "Added from Home Assistant"
            },
            blocking=True
        )


class BabyTrackerNursingButton(BabyTrackerButton):
    """
    Buttons for a nursing timer, like Start/End Sleep: Start Nursing Left/Right begin timing
    (pressing the other side switches to it), End Nursing logs the minutes on each side.
    """

    def __init__(self, coordinator, baby_name, key, side):
        """Initialize the button."""
        super().__init__(coordinator)
        self._baby_name = baby_name
        self._baby_id = coordinator.baby_id_for(baby_name)
        self._side = side  # "left", "right", or None for End Nursing

        self._attr_has_entity_name = True
        self._attr_translation_key = key
        self._attr_unique_id = baby_unique_id(coordinator, baby_name, key)
        self._attr_device_info = baby_device_info(coordinator, baby_name)

    async def _press(self) -> None:
        coordinator = self.coordinator
        if self._side:
            _LOGGER.info(f"Nursing on the {self._side} started for {self._baby_name}")
            coordinator.start_nursing(self._baby_id, self._side)
            return

        totals = coordinator.nursing_totals(self._baby_id)
        if totals is None:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_nursing_timer")
        _LOGGER.info(f"Nursing ended for {self._baby_name}: left {totals['left']} min, right {totals['right']} min")

        await self.hass.services.async_call(
            DOMAIN,
            "add_nursing",
            {
                "baby_name": self._baby_name,
                # The session is dated when it started
                "time": totals["started_at"],
                "left_duration": min(totals["left"], 120),
                "right_duration": min(totals["right"], 120),
                "finish_side": totals["side"].capitalize(),
                "note": "Added from Home Assistant"
            },
            blocking=True
        )
        # Only once it is logged; if that failed, the timer keeps running so End Nursing can be pressed again
        coordinator.clear_nursing(self._baby_id)


class BabyTrackerTummyTimeButton(BabyTrackerButton):
    """Button to log tummy time for the baby's Tummy Time Minutes."""

    def __init__(self, coordinator, baby_name):
        """Initialize the button."""
        super().__init__(coordinator)
        self._baby_name = baby_name
        self._baby_id = coordinator.baby_id_for(baby_name)

        self._attr_has_entity_name = True
        self._attr_translation_key = "log_tummy_time"
        self._attr_unique_id = baby_unique_id(coordinator, baby_name, "log_tummy_time")
        self._attr_device_info = baby_device_info(coordinator, baby_name)

    async def _press(self) -> None:
        minutes = int(self.coordinator.control(self._baby_id, "tummy_time_minutes"))
        _LOGGER.info(f"Logging {minutes} minutes of tummy time for {self._baby_name}")

        await self.hass.services.async_call(
            DOMAIN,
            "log_activity",
            {
                "baby_name": self._baby_name,
                "activity_name": "Tummy Time",
                "duration": minutes,
                "note": "Added from Home Assistant"
            },
            blocking=True
        )


class BabyTrackerBottleButton(BabyTrackerButton):
    """Button to quickly add a bottle of a specific size."""

    # Superseded by the Add Bottle button; kept for dashboards that use them, but not added to new installs
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator, baby_name, size_label, amount_oz):
        """Initialize the button."""
        super().__init__(coordinator)
        self._baby_name = baby_name
        self._size_label = size_label
        self._amount_oz = amount_oz

        self._attr_has_entity_name = True
        self._attr_translation_key = "add_bottle"
        self._attr_translation_placeholders = {"size": size_label}
        self._attr_unique_id = baby_unique_id(coordinator, baby_name, f"add_{size_label.lower()}_bottle")

        self._attr_device_info = baby_device_info(coordinator, baby_name)

    async def _press(self) -> None:
        _LOGGER.info(f"Adding {self._size_label} bottle for {self._baby_name}")

        # Call the add_formula service
        await self.hass.services.async_call(
            DOMAIN,
            "add_formula",
            {
                "baby_name": self._baby_name,
                "amount": self._amount_oz,
                "is_english_measure": True,
                "note": "Added from Home Assistant"
            },
            blocking=True
        )


class BabyTrackerDiaperButton(BabyTrackerButton):
    """Button to quickly add a diaper change."""

    def __init__(self, coordinator, baby_name, diaper_type, pee, poo):
        """Initialize the button."""
        super().__init__(coordinator)
        self._baby_name = baby_name
        self._diaper_type = diaper_type
        self._pee = pee
        self._poo = poo

        safe_type = diaper_type.lower()
        self._attr_has_entity_name = True
        self._attr_translation_key = "add_diaper"
        self._attr_translation_placeholders = {"type": diaper_type}
        self._attr_unique_id = baby_unique_id(coordinator, baby_name, f"add_{safe_type}_diaper")

        self._attr_device_info = baby_device_info(coordinator, baby_name)

    async def _press(self) -> None:
        _LOGGER.info(f"Adding {self._diaper_type} diaper for {self._baby_name}")

        # Call the add_diaper service
        await self.hass.services.async_call(
            DOMAIN,
            "add_diaper",
            {
                "baby_name": self._baby_name,
                "pee": self._pee,
                "poo": self._poo,
                "note": "Added from Home Assistant"
            },
            blocking=True
        )


class BabyTrackerBathButton(BabyTrackerButton):
    """Button to quickly log a bath."""

    def __init__(self, coordinator, baby_name, label):
        """Initialize the button."""
        super().__init__(coordinator)
        self._baby_name = baby_name
        self._label = label

        self._attr_has_entity_name = True
        self._attr_translation_key = "log_bath"
        self._attr_unique_id = baby_unique_id(coordinator, baby_name, "log_bath")

        self._attr_device_info = baby_device_info(coordinator, baby_name)

    async def _press(self) -> None:
        _LOGGER.debug(f"BATH BUTTON PRESSED for {self._baby_name}")

        await self.hass.services.async_call(
            DOMAIN,
            "log_bath",
            {
                "baby_name": self._baby_name,
                "bath_type": None,  # No specific type - just a general bath
                "note": "Added from Home Assistant"
            },
            blocking=True
        )


class BabyTrackerSleepButton(BabyTrackerButton):
    """Button to start or end sleep tracking."""

    def __init__(self, coordinator, baby_name, label, is_start):
        """Initialize the button."""
        super().__init__(coordinator)
        self._baby_name = baby_name
        self._label = label
        self._is_start = is_start

        action = "start" if is_start else "end"
        self._attr_has_entity_name = True
        self._attr_translation_key = f"{action}_sleep"
        self._attr_unique_id = baby_unique_id(coordinator, baby_name, f"{action}_sleep")

        self._attr_device_info = baby_device_info(coordinator, baby_name)

    async def _press(self) -> None:
        _LOGGER.debug(f"SLEEP BUTTON PRESSED: {self._label} for {self._baby_name}, is_start={self._is_start}")

        await self.hass.services.async_call(
            DOMAIN,
            "log_sleep",
            {
                "baby_name": self._baby_name,
                "is_start": self._is_start,
                "note": "Added from Home Assistant"
            },
            blocking=True
        )


class BabyTrackerMedicineButton(BabyTrackerButton):
    """Button to quickly log a medicine dose."""

    # Superseded by the Give Medicine button; kept for dashboards that use it, but not added to new installs
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator, baby_name, medicine_name, amount):
        """Initialize the button."""
        super().__init__(coordinator)
        self._baby_name = baby_name
        self._medicine_name = medicine_name
        self._amount = amount

        safe_medicine = medicine_name.lower().replace(" ", "_")
        self._attr_has_entity_name = True
        self._attr_translation_key = "give_medicine"
        self._attr_translation_placeholders = {"medicine": medicine_name}
        self._attr_unique_id = baby_unique_id(coordinator, baby_name, f"give_{safe_medicine}")

        self._attr_device_info = baby_device_info(coordinator, baby_name)

    async def _press(self) -> None:
        _LOGGER.debug(f"MEDICINE BUTTON PRESSED: {self._medicine_name} ({self._amount}ml) for {self._baby_name}")

        await self.hass.services.async_call(
            DOMAIN,
            "log_medicine",
            {
                "baby_name": self._baby_name,
                "medicine_name": self._medicine_name,
                "amount": self._amount,
                "note": "Added from Home Assistant"
            },
            blocking=True
        )


class BabyTrackerSyncButton(BabyTrackerButton):
    """Button to sync new records from the server without a full resync."""

    def __init__(self, coordinator):
        """Initialize the button."""
        super().__init__(coordinator)

        self._attr_has_entity_name = True
        self._attr_translation_key = "sync_now"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_unique_id = f"{DOMAIN}_{coordinator.email}_sync_now"

        self._attr_device_info = system_device_info(coordinator)

    async def _press(self) -> None:
        """Sync new transactions then refresh data."""
        _LOGGER.info("Sync Now button pressed — fetching new records from server")

        try:
            await self.hass.async_add_executor_job(
                self.coordinator.baby_tracker.sync, self.coordinator.picture_dir
            )
        except Exception as e:
            _LOGGER.error(f"Sync failed: {e}")

        await self.coordinator.async_request_refresh()


class BabyTrackerForceResyncButton(BabyTrackerButton):
    """Button to force a complete resync with the server.

    This is useful when the group leader resets sync and all clients need to reconnect.
    WARNING: This will delete all local data and re-download from server.
    """

    def __init__(self, coordinator):
        """Initialize the button."""
        super().__init__(coordinator)

        self._attr_has_entity_name = True
        self._attr_translation_key = "force_resync"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_unique_id = f"{DOMAIN}_{coordinator.email}_force_resync"

        self._attr_device_info = system_device_info(coordinator)

    async def _press(self) -> None:
        _LOGGER.debug("FORCE RESYNC BUTTON PRESSED - Deleting local database and re-syncing all data")

        # Call the force_resync service
        # Note: The service will reload the config entry, which will recreate all entities
        # After reload, this entity instance will be stale, so we don't try to refresh
        try:
            await self.hass.services.async_call(
                DOMAIN,
                "force_resync",
                {},
                blocking=True
            )
            _LOGGER.debug("FORCE RESYNC BUTTON service call completed - entry was reloaded")
        except Exception as e:
            # This may fail if the entity was unloaded during config entry reload - that's expected
            _LOGGER.debug(f"FORCE RESYNC BUTTON completed (entity may have been reloaded): {str(e)}")
