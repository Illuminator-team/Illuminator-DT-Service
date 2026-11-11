"""Pure helpers for the GeoSphere nwp-v2 forecast source.

Kept free of crawler and pandas imports so the unit tests can load this module directly.
The Dockerfile copies it to /data_crawler/sources/ next to geosphere_nwp_v2.py.
"""
from typing import Any, Dict, Iterable, List, Optional

# Outputs the PV simulators (illuminator-service, pv-sim-service) read from the stream.
SIMULATOR_OUTPUTS = (
    "air_pressure",
    "air_temperature_2m",
    "wind_speed_10m",
    "global_horizontal_irradiation",
)


def parameter_path(parameter: str) -> str:
    """JSONPath to a parameter's data. v2 names such as '2t' and '10u' start with a digit and must be quoted."""
    return f"features[*].properties.parameters.'{parameter}'.data[*]"


def to_interval_start(values: List[Optional[float]]) -> List[Optional[float]]:
    """
    Re-labels hourly means from the end of their hour to its start.

    nwp-v2 gives `ssrd` at timestamp t as the mean over [t - 1h, t]. The v1 source labelled
    the same mean at t - 1h (derivative of an accumulated counter, last value None). Shifting
    keeps the PV simulators' input aligned the way it was with v1.
    """
    if not values:
        return []
    return list(values[1:]) + [None]


def station_pressure_hpa(sea_level_hpa: Iterable[Optional[float]], altitude_m: float) -> List[Optional[float]]:
    """
    Reduces mean sea level pressure to the pressure at the station altitude (standard atmosphere).

    nwp-v2 has no surface pressure (v1 `sp`), only `msl`.
    """
    factor = (1.0 - 0.0065 * altitude_m / 288.15) ** 5.255
    return [None if p is None else p * factor for p in sea_level_hpa]


def incomplete_reason(message: Dict[str, Any], required: Iterable[str] = SIMULATOR_OUTPUTS) -> Optional[str]:
    """Returns why a decoded forecast must not be published, or None if it is complete."""
    times = message.get("observation_time") or []
    if len(times) == 0:
        return "the API returned no forecast time steps"
    for key in required:
        values = message.get(key)
        if values is None:
            return f"'{key}' is missing"
        if len(values) != len(times):
            return f"'{key}' has {len(values)} values for {len(times)} time steps"
        if all(v is None for v in values):
            return f"'{key}' has no values"
    return None
