import json
import tempfile
import time
import unittest
from pathlib import Path

from server import AppState, Calibration, MockSensor, load_profiles


class CalibrationTests(unittest.TestCase):
    def test_linear_calibration_mapping(self) -> None:
        c = Calibration(measured_at_0c=2.0, measured_at_100c=102.0)
        self.assertAlmostEqual(c.apply(2.0), 0.0, places=6)
        self.assertAlmostEqual(c.apply(52.0), 50.0, places=6)
        self.assertAlmostEqual(c.apply(102.0), 100.0, places=6)


class ProfileLoadingTests(unittest.TestCase):
    def test_load_profiles_from_single_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "profiles.json"
            p.write_text(
                json.dumps(
                    [
                        {
                            "id": "p1",
                            "name": "Profile 1",
                            "stages": [{"name": "Drying", "start_sec": 0, "end_sec": 100, "ror_min": 8, "ror_max": 12}],
                        }
                    ]
                ),
                encoding="utf-8",
            )
            profiles = load_profiles(p)
            self.assertEqual(len(profiles), 1)
            self.assertEqual(profiles[0]["id"], "p1")

    def test_load_profiles_from_directory(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "a.json").write_text(
                json.dumps({"id": "a", "name": "A", "stages": []}),
                encoding="utf-8",
            )
            (d / "b.json").write_text(
                json.dumps([
                    {"id": "b1", "name": "B1", "stages": []},
                    {"id": "b2", "name": "B2", "stages": []},
                ]),
                encoding="utf-8",
            )
            profiles = load_profiles(d)
            self.assertEqual({p["id"] for p in profiles}, {"a", "b1", "b2"})

    def test_missing_profile_path_returns_empty(self) -> None:
        missing = Path("/tmp/this-profile-path-should-not-exist-123")
        profiles = load_profiles(missing)
        self.assertEqual(profiles, [])


class MockSensorTests(unittest.TestCase):
    def test_curve_interpolation(self) -> None:
        s = MockSensor(
            {
                "noise_c": 0.0,
                "response": 1.0,
                "cycle_sec": 20,
                "curve": [
                    {"time_sec": 0, "temp_c": 100},
                    {"time_sec": 10, "temp_c": 200},
                    {"time_sec": 20, "temp_c": 100},
                ],
            }
        )
        self.assertAlmostEqual(s._target_for_elapsed(0), 100.0, places=6)
        self.assertAlmostEqual(s._target_for_elapsed(5), 150.0, places=6)
        self.assertAlmostEqual(s._target_for_elapsed(10), 200.0, places=6)
        self.assertAlmostEqual(s._target_for_elapsed(15), 150.0, places=6)


class AppStateTests(unittest.TestCase):
    def _build_config(self) -> dict:
        return {
            "sensor": {
                "mode": "mock",
                "mock": {
                    "noise_c": 0.0,
                    "response": 1.0,
                    "cycle_sec": 100,
                    "curve": [
                        {"time_sec": 0, "temp_c": 50},
                        {"time_sec": 100, "temp_c": 70},
                    ],
                },
            },
            "calibration": {
                "measured_at_0c": 10.0,
                "measured_at_100c": 110.0,
            },
            "ror": {
                "window_sec": 30.0,
                "min_span_sec": 0.5,
                "ema_alpha": 0.3,
            },
        }

    def test_read_temperature_shape_and_calibration(self) -> None:
        state = AppState(self._build_config())
        try:
            data = state.read_temperature()
        finally:
            state.close()

        self.assertTrue(
            {
                "timestamp",
                "raw_c",
                "adjusted_c",
                "ror_c_per_min",
                "ror_raw_c_per_min",
                "ror_ema_alpha",
                "ror_window_sec",
                "sensor_mode",
            }.issubset(data)
        )
        self.assertEqual(data["sensor_mode"], "mock")
        self.assertAlmostEqual(data["adjusted_c"], data["raw_c"] - 10.0, delta=0.5)

    def test_ror_changes_over_time(self) -> None:
        state = AppState(self._build_config())
        try:
            _ = state.read_temperature()
            time.sleep(0.6)
            d2 = state.read_temperature()
        finally:
            state.close()

        self.assertNotEqual(d2["ror_c_per_min"], 0.0)

    def test_ror_ema_smoothing_can_be_disabled(self) -> None:
        cfg = self._build_config()
        cfg["ror"]["ema_alpha"] = 0.0
        state = AppState(cfg)
        try:
            _ = state.read_temperature()
            time.sleep(0.6)
            d2 = state.read_temperature()
        finally:
            state.close()

        self.assertEqual(d2["ror_c_per_min"], d2["ror_raw_c_per_min"])


if __name__ == "__main__":
    unittest.main()
