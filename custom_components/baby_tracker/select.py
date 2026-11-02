"""Select platform for Baby Tracker: per-baby choices the buttons use."""
import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import BOTTLE_TYPE_FORMULA, BOTTLE_TYPE_PUMPED, DOMAIN
from .entity import baby_device_info, baby_unique_id

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up the choices for each baby."""
    coordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        control(coordinator, baby.name)
        for baby in coordinator.data.get("babies") or []
        for control in (BottleTypeSelect, MedicineSelect)
    )


class BabyTrackerSelect(CoordinatorEntity, SelectEntity, RestoreEntity):
    """A choice kept in the coordinator for the buttons to read, restored after a restart."""

    _attr_has_entity_name = True
    _control = None  # the key in the coordinator's controls, and the unique ID suffix and translation key

    def __init__(self, coordinator, baby_name):
        super().__init__(coordinator)
        self._baby_id = coordinator.baby_id_for(baby_name)
        self._attr_translation_key = self._control
        self._attr_unique_id = baby_unique_id(coordinator, baby_name, self._control)
        self._attr_device_info = baby_device_info(coordinator, baby_name)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in self.options:
            self.coordinator.set_control(self._baby_id, self._control, last.state)
            self._restored()

    def _restored(self) -> None:
        """Called after the option was restored."""

    async def async_select_option(self, option: str) -> None:
        self.coordinator.set_control(self._baby_id, self._control, option)
        self.async_write_ha_state()


class BottleTypeSelect(BabyTrackerSelect):
    """Whether the Add Bottle button logs formula or pumped milk."""

    _control = "bottle_type"
    _attr_options = [BOTTLE_TYPE_FORMULA, BOTTLE_TYPE_PUMPED]

    @property
    def current_option(self):
        return self.coordinator.control(self._baby_id, self._control, BOTTLE_TYPE_FORMULA)


class MedicineSelect(BabyTrackerSelect):
    """Which of the account's medicines the Give Medicine button logs."""

    _control = "medicine"

    def _restored(self) -> None:
        # The Medicine Amount takes the restored medicine's usual dose, unless an amount was restored
        # too. The number and select platforms load in either order, so this checks rather than assumes.
        if not self.coordinator.control(self._baby_id, "medicine_amount_restored"):
            self.coordinator.follow_medicine(self._baby_id)

    @property
    def options(self) -> list[str]:
        return self.coordinator.medicine_names

    @property
    def current_option(self):
        return self.coordinator.selected_medicine(self._baby_id)

    async def async_select_option(self, option: str) -> None:
        self.coordinator.set_control(self._baby_id, self._control, option)
        # The Medicine Amount takes this medicine's usual dose
        self.coordinator.follow_medicine(self._baby_id)
        self.async_write_ha_state()
