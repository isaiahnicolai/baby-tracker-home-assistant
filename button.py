"""Button platform for Baby Tracker."""
import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


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
        ])

    async_add_entities(buttons, True)


class BabyTrackerBottleButton(CoordinatorEntity, ButtonEntity):
    """Button to quickly add a bottle of a specific size."""
    
    def __init__(self, coordinator, baby_name, size_label, amount_oz):
        """Initialize the button."""
        super().__init__(coordinator)
        self._baby_name = baby_name
        self._size_label = size_label
        self._amount_oz = amount_oz
        
        safe_baby_name = baby_name.lower().replace(" ", "_")
        self._attr_name = f"{baby_name} Add {size_label} Bottle"
        self._attr_unique_id = f"{DOMAIN}_{coordinator.email}_{safe_baby_name}_add_{size_label.lower()}_bottle"
        self._attr_icon = "mdi:bottle-tonic-plus"
        
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{coordinator.email}_{safe_baby_name}")},
            "name": f"Baby Tracker ({baby_name})",
            "manufacturer": "Baby Tracker",
            "model": "API Integration",
            "sw_version": "0.1.0",
        }
    
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
                "note": f"Quick add {self._size_label}"
            },
            blocking=True
        )
        
        # Refresh coordinator data
        await self.coordinator.async_request_refresh()


class BabyTrackerDiaperButton(CoordinatorEntity, ButtonEntity):
    """Button to quickly add a diaper change."""

    def __init__(self, coordinator, baby_name, diaper_type, pee, poo):
        """Initialize the button."""
        super().__init__(coordinator)
        self._baby_name = baby_name
        self._diaper_type = diaper_type
        self._pee = pee
        self._poo = poo

        safe_baby_name = baby_name.lower().replace(" ", "_")
        safe_type = diaper_type.lower()
        self._attr_name = f"{baby_name} Add {diaper_type} Diaper"
        self._attr_unique_id = f"{DOMAIN}_{coordinator.email}_{safe_baby_name}_add_{safe_type}_diaper"
        self._attr_icon = "mdi:baby-carriage"

        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{coordinator.email}_{safe_baby_name}")},
            "name": f"Baby Tracker ({baby_name})",
            "manufacturer": "Baby Tracker",
            "model": "API Integration",
            "sw_version": "0.1.0",
        }

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
                "note": f"Quick add {self._diaper_type.lower()}"
            },
            blocking=True
        )

        # Refresh coordinator data
        await self.coordinator.async_request_refresh()
