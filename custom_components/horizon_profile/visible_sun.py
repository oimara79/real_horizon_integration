"""Solar crossings of the generated visible horizon profile."""

from bisect import bisect_right
from datetime import date, datetime, time, timedelta, timezone, tzinfo
import math
from typing import Literal, TypedDict

SOLAR_SAMPLE_INTERVAL = timedelta(seconds=30)

VisibleSunEventKey = Literal[
    "sun_next_visible_setting",
    "sun_next_visible_rising",
    "sun_first_visible_sunrise_today",
    "sun_last_visible_sunset_today",
]
SunVisibility = Literal["sun is visible", "sun is not visible"]


class VisibleSunEventData(TypedDict):
    sun_next_visible_setting: datetime | None
    sun_next_visible_rising: datetime | None
    sun_first_visible_sunrise_today: datetime | None
    sun_last_visible_sunset_today: datetime | None
    sun_visible: SunVisibility


def _solar_position(
    when: datetime,
    latitude: float,
    longitude: float,
) -> tuple[float, float]:
    """Return azimuth and geometric elevation in degrees."""
    days_since_j2000 = when.timestamp() / 86400 + 2440587.5 - 2451545
    mean_longitude = (280.46 + 0.9856474 * days_since_j2000) % 360
    mean_anomaly = math.radians((357.528 + 0.9856003 * days_since_j2000) % 360)
    ecliptic_longitude = (
        mean_longitude
        + 1.915 * math.sin(mean_anomaly)
        + 0.02 * math.sin(2 * mean_anomaly)
    )
    obliquity = math.radians(23.439 - 0.0000004 * days_since_j2000)
    ecliptic_radians = math.radians(ecliptic_longitude)
    right_ascension = math.degrees(
        math.atan2(
            math.cos(obliquity) * math.sin(ecliptic_radians),
            math.cos(ecliptic_radians),
        )
    ) % 360
    declination = math.asin(math.sin(obliquity) * math.sin(ecliptic_radians))
    sidereal_time = (
        280.46061837
        + 360.98564736629 * days_since_j2000
        + longitude
    ) % 360
    hour_angle = (sidereal_time - right_ascension + 180) % 360 - 180
    latitude_radians = math.radians(latitude)
    hour_angle_radians = math.radians(hour_angle)
    elevation = math.asin(
        math.sin(latitude_radians) * math.sin(declination)
        + math.cos(latitude_radians)
        * math.cos(declination)
        * math.cos(hour_angle_radians)
    )
    azimuth = (
        math.degrees(
            math.atan2(
                math.sin(hour_angle_radians),
                math.cos(hour_angle_radians) * math.sin(latitude_radians)
                - math.tan(declination) * math.cos(latitude_radians),
            )
        )
        + 180
    ) % 360
    return azimuth, math.degrees(elevation)


def _prepare_profile(profile: list[list[float]]) -> tuple[list[float], list[float]]:
    by_azimuth = {
        float(azimuth) % 360: float(height)
        for azimuth, height in profile
    }
    if not by_azimuth:
        raise ValueError("The horizon profile must contain at least one point.")
    azimuths = sorted(by_azimuth)
    return azimuths, [by_azimuth[azimuth] for azimuth in azimuths]


def _interpolate_horizon(
    azimuth: float,
    profile_azimuths: list[float],
    profile_heights: list[float],
) -> float:
    azimuth %= 360
    index = bisect_right(profile_azimuths, azimuth)
    if index == 0:
        left_azimuth = profile_azimuths[-1] - 360
        left_height = profile_heights[-1]
        right_azimuth = profile_azimuths[0]
        right_height = profile_heights[0]
    elif index == len(profile_azimuths):
        left_azimuth = profile_azimuths[-1]
        left_height = profile_heights[-1]
        right_azimuth = profile_azimuths[0] + 360
        right_height = profile_heights[0]
    else:
        left_azimuth = profile_azimuths[index - 1]
        left_height = profile_heights[index - 1]
        right_azimuth = profile_azimuths[index]
        right_height = profile_heights[index]

    if left_azimuth == right_azimuth:
        return left_height
    ratio = (azimuth - left_azimuth) / (right_azimuth - left_azimuth)
    return left_height + ratio * (right_height - left_height)


def _visible_difference(
    when: datetime,
    latitude: float,
    longitude: float,
    profile_azimuths: list[float],
    profile_heights: list[float],
) -> float:
    azimuth, elevation = _solar_position(when, latitude, longitude)
    return elevation - _interpolate_horizon(
        azimuth,
        profile_azimuths,
        profile_heights,
    )


def _find_day_events(
    local_date: date,
    local_timezone: tzinfo,
    latitude: float,
    longitude: float,
    profile_azimuths: list[float],
    profile_heights: list[float],
) -> list[tuple[str, datetime]]:
    start = datetime.combine(local_date, time.min, tzinfo=local_timezone).astimezone(
        timezone.utc
    )
    end = datetime.combine(
        local_date + timedelta(days=1),
        time.min,
        tzinfo=local_timezone,
    ).astimezone(timezone.utc)

    events: list[tuple[str, datetime]] = []
    previous_time = start
    previous_difference = _visible_difference(
        previous_time,
        latitude,
        longitude,
        profile_azimuths,
        profile_heights,
    )
    current_time = min(previous_time + SOLAR_SAMPLE_INTERVAL, end)

    while current_time <= end:
        difference = _visible_difference(
            current_time,
            latitude,
            longitude,
            profile_azimuths,
            profile_heights,
        )
        previous_visible = previous_difference > 0
        visible = difference > 0
        if previous_visible != visible:
            rising = visible
            lower = previous_time
            upper = current_time
            for _ in range(32):
                middle = lower + (upper - lower) / 2
                middle_visible = (
                    _visible_difference(
                        middle,
                        latitude,
                        longitude,
                        profile_azimuths,
                        profile_heights,
                    )
                    > 0
                )
                if middle_visible == rising:
                    upper = middle
                else:
                    lower = middle
            events.append(("rising" if rising else "setting", upper))

        if current_time == end:
            break
        previous_time = current_time
        previous_difference = difference
        current_time = min(current_time + SOLAR_SAMPLE_INTERVAL, end)

    return events


def calculate_visible_sun_events(
    now: datetime,
    latitude: float,
    longitude: float,
    profile: list[list[float]],
    local_timezone: tzinfo,
) -> VisibleSunEventData:
    """Return the next crossings and first/last crossings for the local day."""
    if now.tzinfo is None:
        raise ValueError("The current time must be timezone-aware.")

    profile_azimuths, profile_heights = _prepare_profile(profile)
    local_now = now.astimezone(local_timezone)
    today = local_now.date()
    sun_visible = (
        _visible_difference(
            now,
            latitude,
            longitude,
            profile_azimuths,
            profile_heights,
        )
        > 0
    )
    today_events = _find_day_events(
        today,
        local_timezone,
        latitude,
        longitude,
        profile_azimuths,
        profile_heights,
    )
    tomorrow_events = _find_day_events(
        today + timedelta(days=1),
        local_timezone,
        latitude,
        longitude,
        profile_azimuths,
        profile_heights,
    )
    future_events = sorted(today_events + tomorrow_events, key=lambda event: event[1])
    now_utc = now.astimezone(timezone.utc)

    return {
        "sun_next_visible_setting": next(
            (
                when
                for event_type, when in future_events
                if event_type == "setting" and when > now_utc
            ),
            None,
        ),
        "sun_next_visible_rising": next(
            (
                when
                for event_type, when in future_events
                if event_type == "rising" and when > now_utc
            ),
            None,
        ),
        "sun_first_visible_sunrise_today": next(
            (when for event_type, when in today_events if event_type == "rising"),
            None,
        ),
        "sun_last_visible_sunset_today": next(
            (
                when
                for event_type, when in reversed(today_events)
                if event_type == "setting"
            ),
            None,
        ),
        "sun_visible": "sun is visible" if sun_visible else "sun is not visible",
    }
