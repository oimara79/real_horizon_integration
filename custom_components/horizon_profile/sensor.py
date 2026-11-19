import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.storage import Store
from homeassistant.components.sensor import SensorEntity

from .cache import cache_matches, make_cache, profile_to_csv
from .const import (
    AZIMUTH_STEP,
    DOMAIN,
    MAX_DISTANCE,
    OBSERVER_HEIGHT,
)
from .horizon import horizon_profile

_LOGGER = logging.getLogger(__name__)
STORAGE_VERSION = 2


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    latitude = float(hass.config.latitude)
    longitude = float(hass.config.longitude)
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ConfigEntryNotReady("Home Assistant latitude or longitude is invalid.")

    store = Store(hass, STORAGE_VERSION, f"{DOMAIN}_{entry.entry_id}")
    cached = await store.async_load()

    if cache_matches(
        cached,
        latitude,
        longitude,
        MAX_DISTANCE,
        AZIMUTH_STEP,
        OBSERVER_HEIGHT,
    ):
        profile = cached["profile"]
        _LOGGER.info("Loaded cached horizon profile for the configured location")
    else:
        _LOGGER.info("Generating horizon profile from Copernicus GLO-30 data")
        try:
            generated = await hass.async_add_executor_job(
                horizon_profile,
                latitude,
                longitude,
                MAX_DISTANCE,
                AZIMUTH_STEP,
                OBSERVER_HEIGHT,
            )
        except (OSError, RuntimeError, ValueError) as err:
            _LOGGER.exception("Could not generate the Copernicus horizon profile")
            raise ConfigEntryNotReady(
                f"Could not generate the horizon profile: {err}"
            ) from err

        profile = [[float(azimuth), float(height)] for azimuth, height in generated]
        await store.async_save(
            make_cache(
                latitude,
                longitude,
                generated,
                MAX_DISTANCE,
                AZIMUTH_STEP,
                OBSERVER_HEIGHT,
            )
        )
        _LOGGER.info("Generated and cached %s horizon measurements", len(profile))

    async_add_entities([HorizonProfileSensor(entry.entry_id, profile)])


class HorizonProfileSensor(SensorEntity):
    _attr_has_entity_name = False
    _attr_icon = "mdi:terrain"
    _attr_name = "Horizon Profile"
    _attr_native_value = "ready"

    def __init__(self, entry_id: str, profile: list[list[float]]) -> None:
        self._attr_unique_id = f"{entry_id}_horizon_profile"
        self._profile_csv = profile_to_csv(profile)

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        return {"profile_csv": self._profile_csv}
