import math
from typing import Any


def cache_matches(
    data: Any,
    latitude: float,
    longitude: float,
    max_distance: float,
    azimuth_step: float,
    observer_height: float,
) -> bool:
    if not isinstance(data, dict):
        return False

    if (
        data.get("latitude") != latitude
        or data.get("longitude") != longitude
        or data.get("max_distance") != max_distance
        or data.get("azimuth_step") != azimuth_step
        or data.get("observer_height") != observer_height
    ):
        return False

    profile = data.get("profile")
    if not isinstance(profile, list) or not profile:
        return False

    for point in profile:
        if not isinstance(point, list) or len(point) != 2:
            return False
        azimuth, height = point
        if (
            not isinstance(azimuth, (int, float))
            or not math.isfinite(azimuth)
            or not 0 <= azimuth <= 360
            or not isinstance(height, (int, float))
            or not math.isfinite(height)
            or not -90 <= height <= 90
        ):
            return False
    return True


def make_cache(
    latitude: float,
    longitude: float,
    profile: list[tuple[float, float]],
    max_distance: float,
    azimuth_step: float,
    observer_height: float,
) -> dict[str, Any]:
    return {
        "latitude": latitude,
        "longitude": longitude,
        "max_distance": max_distance,
        "azimuth_step": azimuth_step,
        "observer_height": observer_height,
        "profile": [[azimuth, height] for azimuth, height in profile],
    }


def profile_to_csv(profile: list[list[float]]) -> str:
    rows = ["azimuth,height"]
    rows.extend(f"{azimuth},{height}" for azimuth, height in profile)
    return "\n".join(rows)
