import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = (
    Path(__file__).parent.parent
    / "custom_components"
    / "horizon_profile"
    / "cache.py"
)
SPEC = importlib.util.spec_from_file_location("horizon_profile_cache", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
CACHE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CACHE)


class HorizonProfileCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = [(90.0, 5.0), (180.0, 12.0), (270.0, 7.0)]
        self.data = CACHE.make_cache(
            47.7,
            12.8,
            self.profile,
            50_000.0,
            1.0,
            0.0,
        )

    def test_cache_matches_same_location_and_generator_settings(self) -> None:
        self.assertTrue(
            CACHE.cache_matches(self.data, 47.7, 12.8, 50_000.0, 1.0, 0.0)
        )
        self.assertFalse(
            CACHE.cache_matches(self.data, 48.0, 12.8, 50_000.0, 1.0, 0.0)
        )
        self.assertFalse(
            CACHE.cache_matches(self.data, 47.7, 12.8, 40_000.0, 1.0, 0.0)
        )
        self.assertFalse(
            CACHE.cache_matches(self.data, 47.7, 12.8, 50_000.0, 0.2, 0.0)
        )

    def test_cache_rejects_invalid_profile_rows(self) -> None:
        invalid = dict(self.data)
        invalid["profile"] = [[90.0, 100.0]]
        self.assertFalse(
            CACHE.cache_matches(invalid, 47.7, 12.8, 50_000.0, 1.0, 0.0)
        )

    def test_profile_is_exported_as_card_csv(self) -> None:
        self.assertEqual(
            CACHE.profile_to_csv(self.data["profile"]),
            "azimuth,height\n90.0,5.0\n180.0,12.0\n270.0,7.0",
        )


if __name__ == "__main__":
    unittest.main()
