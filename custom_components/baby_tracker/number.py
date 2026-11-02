"""Number platform for Baby Tracker: per-baby settings the buttons use."""
import logging

from homeassistant.components.number import NumberMode, RestoreNumber
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DEFAULT_BOTTLE_ML,
    DEFAULT_BOTTLE_OZ,
    DEFAULT_MEDICINE_AMOUNT,
    DEFAULT_TUMMY_TIME_MINUTES,
    DOMAIN,
    UNIT_SYSTEM_METRIC,
    control_signal,
)
from .entity import baby_device_info, baby_unique_id

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up the controls for each baby."""
    coordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        control(coordinator, baby.name)
        for baby in coordinator.data.get("babies") or []
        for control in (BottleSizeNumber, MedicineAmountNumber, TummyTimeNumber)
    )


class BabyTrackerNumber(CoordinatorEntity, RestoreNumber):
    """
    A value kept in the coordinator for the buttons to read. It is restored after
    a restart, so a bottle size set once stays set.
    """

    _attr_has_entity_name = True
    _attr_mode = NumberMode.BOX
    _control = None  # the key in the coordinator's controls, and the unique ID suffix and translation key
    _default = None

    def __init__(self, coordinator, baby_name):
        super().__init__(coordinator)
        self._baby_id = coordinator.baby_id_for(baby_name)
        self._attr_translation_key = self._control
        self._attr_unique_id = baby_unique_id(coordinator, baby_name, self._control)
        self._attr_device_info = baby_device_info(coordinator, baby_name)
        self._configure()
        coordinator.set_control(self._baby_id, self._control, self._default)

    def _configure(self):
        """Set the range, step and unit (a subclass whose range depends on the entry's settings overrides this)."""

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        # A value saved in another unit (the entry was switched between oz and mL) means nothing now
        if (
            last is not None
            and last.native_value is not None
            and last.native_unit_of_measurement == self.native_unit_of_measurement
            and self.native_min_value <= last.native_value <= self.native_max_value
        ):
            self.coordinator.set_control(self._baby_id, self._control, last.native_value)
            # A value the user set wins over a medicine's usual dose (see MedicineSelect)
            self.coordinator.set_control(self._baby_id, f"{self._control}_restored", True)

    @property
    def native_value(self):
        value = self.coordinator.control(self._baby_id, self._control)
        # Doses copied from the app are single-precision floats (0.300000011920929)
        return round(value, 3) if isinstance(value, float) else value

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.set_control(self._baby_id, self._control, value)
        self.async_write_ha_state()


class BottleSizeNumber(BabyTrackerNumber):
    """How much the Add Bottle button logs: ounces, or millilitres when the entry is metric."""

    _control = "bottle_size"

    def _configure(self):
        if self.coordinator.unit_system == UNIT_SYSTEM_METRIC:
            self._attr_native_unit_of_measurement = "mL"
            self._attr_native_min_value, self._attr_native_max_value, self._attr_native_step = 30, 360, 10
            self._default = DEFAULT_BOTTLE_ML
        else:
            self._attr_native_unit_of_measurement = "oz"
            self._attr_native_min_value, self._attr_native_max_value, self._attr_native_step = 1, 12, 0.5
            self._default = DEFAULT_BOTTLE_OZ


class MedicineAmountNumber(BabyTrackerNumber):
    """How much the Give Medicine button logs, in the selected medicine's own unit."""

    _control = "medicine_amount"
    _default = DEFAULT_MEDICINE_AMOUNT
    _attr_native_min_value = 0.1
    _attr_native_max_value = 100
    _attr_native_step = 0.1

    def _configure(self):
        # Start at the usual dose of the medicine the Medicine select starts on
        self._default = self.coordinator.medicine_dose(self._baby_id) or DEFAULT_MEDICINE_AMOUNT

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Choosing a medicine sets this value (and changes the unit shown) from outside
        self.async_on_remove(async_dispatcher_connect(
            self.hass, control_signal(self.coordinator.config_entry.entry_id), self._handle_control))

    @callback
    def _handle_control(self, baby_id, control) -> None:
        if baby_id == self._baby_id and control == self._control:
            self.async_write_ha_state()

    @property
    def extra_state_attributes(self):
        """The unit of the selected medicine's amounts (ml, tablet...), when the app has one."""
        unit = (self.coordinator.selected_medicine_info(self._baby_id) or {}).get("unit")
        return {"unit": unit} if unit else {}


class TummyTimeNumber(BabyTrackerNumber):
    """How long the Log Tummy Time button logs."""

    _control = "tummy_time_minutes"
    _default = DEFAULT_TUMMY_TIME_MINUTES
    _attr_native_min_value = 1
    _attr_native_max_value = 120
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
