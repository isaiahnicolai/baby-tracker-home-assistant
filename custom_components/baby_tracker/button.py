"""Button platform for Baby Tracker."""
import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
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


class BabyTrackerBottleButton(CoordinatorEntity, ButtonEntity):
    """Button to quickly add a bottle of a specific size."""

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

    async def async_press(self) -> None:
        """Handle button press."""
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


class BabyTrackerDiaperButton(CoordinatorEntity, ButtonEntity):
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

    async def async_press(self) -> None:
        """Handle button press."""
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


class BabyTrackerBathButton(CoordinatorEntity, ButtonEntity):
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

    async def async_press(self) -> None:
        """Handle button press."""
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


class BabyTrackerSleepButton(CoordinatorEntity, ButtonEntity):
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

    async def async_press(self) -> None:
        """Handle button press."""
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


class BabyTrackerMedicineButton(CoordinatorEntity, ButtonEntity):
    """Button to quickly log a medicine dose."""

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

    async def async_press(self) -> None:
        """Handle button press."""
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


class BabyTrackerSyncButton(CoordinatorEntity, ButtonEntity):
    """Button to sync new records from the server without a full resync."""

    def __init__(self, coordinator):
        """Initialize the button."""
        super().__init__(coordinator)

        self._attr_has_entity_name = True
        self._attr_translation_key = "sync_now"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_unique_id = f"{DOMAIN}_{coordinator.email}_sync_now"

        self._attr_device_info = system_device_info(coordinator)

    async def async_press(self) -> None:
        """Handle button press — sync new transactions then refresh data."""
        _LOGGER.info("Sync Now button pressed — fetching new records from server")

        try:
            await self.hass.async_add_executor_job(
                self.coordinator.baby_tracker.sync, self.coordinator.picture_dir
            )
        except Exception as e:
            _LOGGER.error(f"Sync failed: {e}")

        await self.coordinator.async_request_refresh()


class BabyTrackerForceResyncButton(CoordinatorEntity, ButtonEntity):
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

    async def async_press(self) -> None:
        """Handle button press."""
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
