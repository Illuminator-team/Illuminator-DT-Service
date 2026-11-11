"""
GeoSphere AROME forecasts from the nwp-v2-1h-1km dataset.

The crawler image only knows nwp-v1-1h-2500m, which stopped publishing on 2026-11-04 (issue #48).
This source reuses the v1 class and maps the v2 parameters onto the same output names, so the
Redis stream keeps the fields the PV simulators and Grafana read:

    air_temperature_2m              <- 2t   [degC]
    air_pressure                    <- msl  [Pa -> hPa], reduced to `altitude`
    wind_speed_10m                  <- 10u, 10v  [m s-1]
    global_horizontal_irradiation   <- ssrd [W m-2], labelled at the start of its hour like v1

A response without time steps, or without one of the required outputs, is logged and not published.
"""
from typing import Any, Dict, List, Optional

import data_crawler.access.jsonpath as jx
import data_crawler.sources.zamg as zamg
from data_crawler.sources import nwp_v2_transform as transform

_SSRD_KEY = "_global_horizontal_irradiation_preceding_hour"


class NumericalWeatherPredictionV2Data(zamg.NumericalWeatherPredictionData):
    """
    AROME NWP v2 access. Metadata: https://dataset.api.hub.geosphere.at/v1/timeseries/forecast/nwp-v2-1h-1km/metadata

    Extra source parameters:
      altitude: station altitude in metres for the msl -> air_pressure reduction (default 0)
      required outputs: outputs that must be present to publish (default: the simulator inputs)
    """

    _endpoint_configs = {
        "nwp-v2": zamg._EndpointConfig(parameter_mapping={
            "2t": zamg._PRef("air_temperature_2m"),  # [degC]
            "2r": zamg._PRef("relative_humidity_2m"),  # [%]
            "msl": zamg._PRef("air_pressure_at_sea_level", scaling=0.01),  # [Pa] -> [hPa]
            "ssrd": zamg._PRef(_SSRD_KEY),  # [W m-2] mean over the hour ending at the timestamp
            "10u": zamg._PRef("_wind_speed_u_10m"),  # [m s-1] eastward
            "10v": zamg._PRef("_wind_speed_v_10m"),  # [m s-1] northward
            "10fg": zamg._PRef("wind_speed_gust_10m"),  # [m s-1] max gust in the last interval
            "tcc": zamg._PRef("cloud_area_fraction"),  # [%]
        }, type="timeseries", mode="forecast", resource_id="nwp-v2-1h-1km"),
    }

    def __init__(self, source_parameters, executor_name, **kwargs):
        super(NumericalWeatherPredictionV2Data, self).__init__(source_parameters=source_parameters,
                                                               executor_name=executor_name, **kwargs)
        self._altitude = float(source_parameters.get("altitude", 0.0))
        self._required_outputs = tuple(source_parameters.get("required outputs", transform.SIMULATOR_OUTPUTS))

    def _get_extractors(self, data_points: List[str]) -> List[jx.PathExtractor]:
        """Same extractors as v1, but with quoted parameter paths."""

        extractors = [
            jx.PathExtractor("longitude", "features[*].geometry.coordinates[0]", is_list=False),
            jx.PathExtractor("latitude", "features[*].geometry.coordinates[1]", is_list=False),
            jx.DatetimePathExtractor("observation_time", "timestamps[*]", is_list=True),
            jx.PathExtractor("forecast_time", "reference_time", is_list=False),
        ]
        for data_point in data_points:
            reference = self._local_mapping[data_point]
            extractors.append(jx.PathExtractor(
                reference.name, transform.parameter_path(data_point),
                is_list=True, dst_format=lambda x, sc=reference.scaling: (x * sc if x is not None else None),
                drop_missing=True
            ))
        return extractors

    def fetch_data(self, raw_data: Optional[dict] = None) -> Optional[Dict[str, Any]]:
        """Fetches the latest forecast; returns None (nothing is published) if it is empty or incomplete."""

        message = self.fetch_message(raw_data=raw_data)
        if not message.get("observation_time"):
            self.logger.warning(f"Not publishing forecast {message.get('forecast_time')}: "
                                "the API returned no forecast time steps.")
            return None

        if _SSRD_KEY in message:
            message["global_horizontal_irradiation"] = transform.to_interval_start(message[_SSRD_KEY])
        if "air_pressure_at_sea_level" in message:
            message["air_pressure"] = transform.station_pressure_hpa(message["air_pressure_at_sea_level"],
                                                                     self._altitude)
        message = self._extend_computed_outputs(message)

        reason = transform.incomplete_reason(message, self._required_outputs)
        if reason is not None:
            self.logger.warning(f"Not publishing forecast {message.get('forecast_time')}: {reason}.")
            return None
        return message
