import logging
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)
from homeassistant.util import dt as dt_util

from .cache import cache_matches, make_cache, profile_to_csv
from .const import (
    AZIMUTH_STEP,
    DOMAIN,
    MAX_DISTANCE,
    OBSERVER_HEIGHT,
)
from .horizon import horizon_profile
from .visible_sun import (
    VisibleSunEventData,
    VisibleSunEventKey,
    calculate_visible_sun_events,
)

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
    local_timezone = dt_util.get_time_zone(hass.config.time_zone)
    if local_timezone is None:
        raise ConfigEntryNotReady("Home Assistant time zone is invalid.")

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

    async def async_update_sun_events() -> VisibleSunEventData:
        return await hass.async_add_executor_job(
            calculate_visible_sun_events,
            dt_util.now(),
            latitude,
            longitude,
            profile,
            local_timezone,
        )

    coordinator: DataUpdateCoordinator[VisibleSunEventData] = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"{DOMAIN} visible sun events",
        update_method=async_update_sun_events,
        update_interval=timedelta(minutes=1),
    )
    await coordinator.async_config_entry_first_refresh()

    async_add_entities(
        [
            HorizonProfileSensor(entry.entry_id, profile),
            VisibleSunEventSensor(
                coordinator,
                entry.entry_id,
                "sun_next_visible_setting",
                "Sun Next Visible Setting",
                "mdi:weather-sunset-down",
            ),
            VisibleSunEventSensor(
                coordinator,
                entry.entry_id,
                "sun_next_visible_rising",
                "Sun Next Visible Rising",
                "mdi:weather-sunset-up",
            ),
            VisibleSunEventSensor(
                coordinator,
                entry.entry_id,
                "sun_first_visible_sunrise_today",
                "Sun First Visible Sunrise Today",
                "mdi:weather-sunset-up",
            ),
            VisibleSunEventSensor(
                coordinator,
                entry.entry_id,
                "sun_last_visible_sunset_today",
                "Sun Last Visible Sunset Today",
                "mdi:weather-sunset-down",
            ),
            SunVisibilitySensor(coordinator, entry.entry_id),
        ]
    )


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


class VisibleSunEventSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = False
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(
        self,
        coordinator: DataUpdateCoordinator[VisibleSunEventData],
        entry_id: str,
        event_key: VisibleSunEventKey,
        name: str,
        icon: str,
    ) -> None:
        super().__init__(coordinator)
        self._event_key = event_key
        self._attr_unique_id = f"{entry_id}_{event_key}"
        self._attr_name = name
        self._attr_icon = icon

    @property
    def native_value(self) -> datetime | None:
        return self.coordinator.data[self._event_key]


class SunVisibilitySensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = False
    _attr_icon = "mdi:weather-sunny"
    _attr_name = "Sun Visible"

    def __init__(
        self,
        coordinator: DataUpdateCoordinator[VisibleSunEventData],
        entry_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry_id}_sun_visible"

    @property
    def native_value(self) -> str:
        return self.coordinator.data["sun_visible"]
