import importlib.util
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


MODULE_PATH = (
    Path(__file__).parent.parent
    / "custom_components"
    / "horizon_profile"
    / "visible_sun.py"
)
SPEC = importlib.util.spec_from_file_location(
    "horizon_profile_visible_sun",
    MODULE_PATH,
)
assert SPEC is not None and SPEC.loader is not None
VISIBLE_SUN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VISIBLE_SUN)


class VisibleSunEventTests(unittest.TestCase):
    def test_flat_horizon_returns_next_and_daily_events(self) -> None:
        now = datetime.fromisoformat("2024-03-20T12:00:00+00:00")
        result = VISIBLE_SUN.calculate_visible_sun_events(
            now,
            0.0,
            0.0,
            [[0, 0], [90, 0], [180, 0], [270, 0]],
            ZoneInfo("UTC"),
        )

        next_setting = result["sun_next_visible_setting"]
        next_rising = result["sun_next_visible_rising"]
        self.assertEqual(next_setting.date().isoformat(), "2024-03-20")
        self.assertEqual(next_rising.date().isoformat(), "2024-03-21")
        sunrise = result["sun_first_visible_sunrise_today"]
        sunset = result["sun_last_visible_sunset_today"]
        self.assertIsNotNone(sunrise)
        self.assertIsNotNone(sunset)
        self.assertEqual(sunrise.date().isoformat(), "2024-03-20")
        self.assertEqual(sunset.date().isoformat(), "2024-03-20")
        self.assertLess(sunrise.hour, 8)
        self.assertGreater(sunset.hour, 16)

    def test_terrain_ridge_can_create_multiple_visible_crossings(self) -> None:
        result = VISIBLE_SUN.calculate_visible_sun_events(
            datetime.fromisoformat("2024-06-21T06:00:00+00:00"),
            45.0,
            0.0,
            [[0, 0], [90, 0], [100, 60], [170, 60], [180, 0], [270, 0]],
            ZoneInfo("UTC"),
        )

        first_sunrise = result["sun_first_visible_sunrise_today"]
        next_setting = result["sun_next_visible_setting"]
        next_rising = result["sun_next_visible_rising"]
        last_sunset = result["sun_last_visible_sunset_today"]
        self.assertLess(first_sunrise, next_setting)
        self.assertLess(next_setting, next_rising)
        self.assertLess(next_rising, last_sunset)

    def test_visibility_state_uses_the_horizon_at_the_current_sun_position(self) -> None:
        profile = [[0, 0], [90, 0], [100, 60], [170, 60], [180, 0], [270, 0]]
        visible = VISIBLE_SUN.calculate_visible_sun_events(
            datetime.fromisoformat("2024-06-21T06:00:00+00:00"),
            45.0,
            0.0,
            profile,
            ZoneInfo("UTC"),
        )
        behind_ridge = VISIBLE_SUN.calculate_visible_sun_events(
            datetime.fromisoformat("2024-06-21T09:00:00+00:00"),
            45.0,
            0.0,
            profile,
            ZoneInfo("UTC"),
        )

        self.assertEqual(visible["sun_visible"], "sun is visible")
        self.assertEqual(behind_ridge["sun_visible"], "sun is not visible")

    def test_local_day_events_follow_daylight_saving_time(self) -> None:
        local_timezone = ZoneInfo("America/New_York")
        result = VISIBLE_SUN.calculate_visible_sun_events(
            datetime.fromisoformat("2024-03-10T12:00:00-04:00"),
            40.7,
            -74.0,
            [[0, 0], [90, 0], [180, 0], [270, 0]],
            local_timezone,
        )

        sunrise = result["sun_first_visible_sunrise_today"]
        sunset = result["sun_last_visible_sunset_today"]
        local_sunrise = sunrise.astimezone(local_timezone)
        local_sunset = sunset.astimezone(local_timezone)
        self.assertEqual(local_sunrise.date().isoformat(), "2024-03-10")
        self.assertEqual(local_sunset.date().isoformat(), "2024-03-10")
        self.assertEqual(local_sunrise.utcoffset().total_seconds(), -4 * 3600)

    def test_absent_crossings_are_reported_as_none(self) -> None:
        result = VISIBLE_SUN.calculate_visible_sun_events(
            datetime.fromisoformat("2024-06-21T12:00:00+00:00"),
            45.0,
            0.0,
            [[0, 90], [90, 90], [180, 90], [270, 90]],
            ZoneInfo("UTC"),
        )

        self.assertEqual(
            {key: value for key, value in result.items() if key != "sun_visible"},
            {
                "sun_next_visible_setting": None,
                "sun_next_visible_rising": None,
                "sun_first_visible_sunrise_today": None,
                "sun_last_visible_sunset_today": None,
            },
        )
        self.assertEqual(result["sun_visible"], "sun is not visible")

    def test_rejects_naive_current_time(self) -> None:
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            VISIBLE_SUN.calculate_visible_sun_events(
                datetime(2024, 3, 20, 12),
                0.0,
                0.0,
                [[0, 0], [180, 0]],
                ZoneInfo("UTC"),
            )


if __name__ == "__main__":
    unittest.main()
