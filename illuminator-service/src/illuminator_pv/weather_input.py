"""Checks a weather forecast entry from Redis before the simulator uses it (issue #48)."""
import json
from typing import Any, Mapping, Optional

FORECAST_FIELDS = ("station", "forecast_time", "observation_time", "latitude", "longitude")
SERIES_FIELDS = ("air_pressure", "air_temperature_2m", "wind_speed_10m", "global_horizontal_irradiation")


def _as_list(value: Any) -> Optional[list]:
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, list) else None


def incomplete_forecast_reason(weather_data: Mapping[str, Any]) -> Optional[str]:
    """Returns why the forecast cannot be simulated, or None if it is complete."""
    missing = [k for k in FORECAST_FIELDS + SERIES_FIELDS if k not in weather_data]
    if missing:
        return f"missing fields {missing}"

    times = _as_list(weather_data["observation_time"])
    if not times:
        return "no forecast time steps"

    for key in SERIES_FIELDS:
        values = _as_list(weather_data[key])
        if values is None:
            return f"'{key}' is not a list"
        if len(values) != len(times):
            return f"'{key}' has {len(values)} values for {len(times)} time steps"
        if all(v is None for v in values):
            return f"'{key}' has no values"

    try:
        float(weather_data["latitude"])
        float(weather_data["longitude"])
    except (TypeError, ValueError):
        return "latitude/longitude are not numbers"
    return None
