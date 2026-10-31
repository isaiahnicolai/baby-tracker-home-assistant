"""Image platform for Baby Tracker: each baby's photo, served only to logged-in users."""
import mimetypes

from homeassistant.components.image import ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
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
    """Set up an image entity for each baby, and a landscape one for each baby that has a landscape photo."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    pictures = coordinator.data.get("baby_pictures") or {}
    babies = coordinator.data.get("babies") or []
    async_add_entities(BabyTrackerPhoto(hass, coordinator, baby.name) for baby in babies)
    async_add_entities(
        BabyTrackerLandscapePhoto(hass, coordinator, baby.name)
        for baby in babies
        if (pictures.get(baby.name) or {}).get("landscape")
    )


def _read(path):
    with open(path, "rb") as photo:
        return photo.read()


class BabyTrackerPhoto(CoordinatorEntity, ImageEntity):
    """
    A baby's photo from the app. The file lives in a private folder in the
    Home Assistant config directory, not under www, so it is only served
    through this entity (which needs a login or the entity's access token).
    """

    _attr_has_entity_name = True
    _attr_translation_key = "baby_photo"

    def __init__(self, hass, coordinator, baby_name):
        """Initialize the image."""
        CoordinatorEntity.__init__(self, coordinator)
        ImageEntity.__init__(self, hass)
        self._baby_name = baby_name
        self._path = None
        self._attr_unique_id = baby_unique_id(coordinator, baby_name, "photo")
        self._attr_device_info = baby_device_info(coordinator, baby_name)
        self._use_photo_from_data()

    def _use_photo_from_data(self):
        """Take this baby's current photo (file and modification time) from the coordinator's data."""
        photo = self._picture(((self.coordinator.data or {}).get("baby_pictures") or {}).get(self._baby_name))
        self._path = photo["path"] if photo else None
        # image_last_updated is what tells the frontend the picture has changed
        self._attr_image_last_updated = photo["updated"] if photo else None
        self._attr_content_type = (mimetypes.guess_type(self._path)[0] if self._path else None) or "image/jpeg"

    def _picture(self, pictures):
        """Which of the baby's downloaded pictures this entity shows (a {"path", "updated"} dict, or None)."""
        return pictures if pictures and pictures.get("path") else None

    @callback
    def _handle_coordinator_update(self) -> None:
        self._use_photo_from_data()
        super()._handle_coordinator_update()

    async def async_image(self) -> bytes | None:
        """Return the photo's bytes, or None when the baby has no photo."""
        if not self._path:
            return None
        try:
            return await self.hass.async_add_executor_job(_read, self._path)
        except OSError:
            return None


class BabyTrackerLandscapePhoto(BabyTrackerPhoto):
    """The app's landscape version of the baby's photo (the wide crop), when the baby has one."""

    _attr_translation_key = "baby_photo_landscape"

    def __init__(self, hass, coordinator, baby_name):
        """Initialize the image."""
        super().__init__(hass, coordinator, baby_name)
        self._attr_unique_id = baby_unique_id(coordinator, baby_name, "photo_landscape")

    def _picture(self, pictures):
        return (pictures or {}).get("landscape")
