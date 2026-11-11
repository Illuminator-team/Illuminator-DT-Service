"""Weather forecast input (issue #48): nwp-v2 mapping helpers and the simulators' completeness check."""
import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "weather-data-service"))

import nwp_v2_transform as transform  # noqa: E402

SIMULATOR_COPIES = (
    ROOT / "illuminator-service" / "src" / "illuminator_pv" / "weather_input.py",
    ROOT / "pv-sim-service" / "src" / "pv_sim" / "weather_input.py",
)


def load(path):
    spec = importlib.util.spec_from_file_location(f"weather_input_{path.parent.name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def redis_entry(n=3, **overrides):
    """A stream entry as the simulators read it (all values are strings)."""
    entry = {
        "station": '"11035"',
        "forecast_time": '"2026-11-11T03:00:00+00:00"',
        "observation_time": json.dumps([f"2026-11-11T{10 + i:02d}:00:00+00:00" for i in range(n)]),
        "air_pressure": json.dumps([990.0] * n),
        "air_temperature_2m": json.dumps([4.0] * n),
        "wind_speed_10m": json.dumps([2.5] * n),
        "global_horizontal_irradiation": json.dumps([50.0] * (n - 1) + [None]),
        "latitude": "48.249",
        "longitude": "16.358",
    }
    entry.update(overrides)
    return {k: v for k, v in entry.items() if v is not None}


# What the old crawler kept publishing after nwp-v1 stopped: metadata, no time steps, no fields.
EMPTY_V1_ENTRY = {
    "station": '"11035"',
    "forecast_time": '"2026-11-04T03:00:00+00:00"',
    "observation_time": "[]",
    "latitude": "48.255",
    "longitude": "16.362",
    "data_provider": '"ZAMG.NWP"',
}


class TransformTest(unittest.TestCase):
    def test_parameter_path_quotes_names_starting_with_a_digit(self):
        self.assertEqual(transform.parameter_path("2t"), "features[*].properties.parameters.'2t'.data[*]")

    def test_irradiation_is_labelled_at_the_start_of_its_hour(self):
        self.assertEqual(transform.to_interval_start([10.0, 20.0, 30.0]), [20.0, 30.0, None])
        self.assertEqual(transform.to_interval_start([]), [])

    def test_sea_level_pressure_is_reduced_to_station_altitude(self):
        reduced = transform.station_pressure_hpa([1013.25, None], 198.0)
        self.assertAlmostEqual(reduced[0], 989.6, delta=0.2)
        self.assertIsNone(reduced[1])
        self.assertEqual(transform.station_pressure_hpa([1000.0], 0.0), [1000.0])

    def test_incomplete_messages_are_not_published(self):
        complete = {"observation_time": ["a", "b"], **{k: [1.0, None] for k in transform.SIMULATOR_OUTPUTS}}
        self.assertIsNone(transform.incomplete_reason(complete))
        self.assertIn("no forecast time steps", transform.incomplete_reason({"observation_time": []}))
        for key in transform.SIMULATOR_OUTPUTS:
            missing = dict(complete)
            del missing[key]
            self.assertIn(key, transform.incomplete_reason(missing))
            self.assertIn("no values", transform.incomplete_reason({**complete, key: [None, None]}))
            self.assertIn("1 values", transform.incomplete_reason({**complete, key: [1.0]}))


class SimulatorWeatherInputTest(unittest.TestCase):
    def test_both_simulators_use_the_same_check(self):
        self.assertEqual(SIMULATOR_COPIES[0].read_bytes(), SIMULATOR_COPIES[1].read_bytes())

    def test_check(self):
        for path in SIMULATOR_COPIES:
            check = load(path).incomplete_forecast_reason
            with self.subTest(path=path.parent.name):
                self.assertIsNone(check(redis_entry()))
                self.assertIn("missing fields", check(EMPTY_V1_ENTRY))
                self.assertIn("air_pressure", check(EMPTY_V1_ENTRY))
                self.assertIn("no forecast time steps", check(redis_entry(observation_time="[]")))
                self.assertIn("air_pressure", check(redis_entry(air_pressure=None)))
                self.assertIn("2 values", check(redis_entry(wind_speed_10m=json.dumps([1.0, 2.0]))))
                self.assertIn("no values", check(redis_entry(air_temperature_2m=json.dumps([None] * 3))))
                self.assertIn("not a list", check(redis_entry(global_horizontal_irradiation="oops")))
                self.assertIn("latitude", check(redis_entry(latitude="null")))


if __name__ == "__main__":
    unittest.main()
