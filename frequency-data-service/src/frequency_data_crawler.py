import data_crawler.sources.abc.http_cache as http_cache
import data_crawler.access.jsonpath as jx

import itertools
import posixpath
import requests

from datetime import datetime, timedelta, timezone
from typing import Any, Dict

class FrequencyDataCrawler(http_cache.GenericHTTPSourceAPI):
    """Queries the flex forecast from HPT"""

    DEFAULT_BASE_URL : str = 'https://api.energy-charts.info'
    DEFAULT_SERVICE_ENDPOINT : str = 'frequency'
    DEFAULT_REGION : str = 'UCTE'
    DEFAULT_TIME_LAG_S : int = 300

    def __init__(self, source_parameters, **kwargs):
        """
        Initializes the API but does not trigger any query

        :param source_parameters: The source parameters according to the configuration
        :param kwargs: Any extra arguments that will be sent to the super class
        """
        super(FrequencyDataCrawler, self).__init__(source_parameters=source_parameters, **kwargs)
        self._base_url : str = source_parameters.get('base_url', self.DEFAULT_BASE_URL)
        self._service_endpoint : str = source_parameters.get('service_endpoint', self.DEFAULT_SERVICE_ENDPOINT).strip('/')
        self._region : str = source_parameters.get('region', self.DEFAULT_REGION)
        self._time_lag_s : int = source_parameters.get('time_lag_s', self.DEFAULT_TIME_LAG_S)

    @property
    def request_url(self) -> str:
        """
        Returns the request URL
        """
        return posixpath.join(self._base_url, self._service_endpoint)

    @property
    def request_parameters(self) -> Dict[str, str]:
        """
        Returns the request parameters
        """
        now = datetime.now(tz=timezone.utc)
        measurement_time = now - timedelta(seconds=self._time_lag_s)

        return dict(
            region=self._region,
            start=measurement_time.isoformat(timespec="seconds"),
            end=measurement_time.isoformat(timespec="seconds"),
        )

    def fetch_data(self, raw_forecast=None) -> Dict[str, Any]:
        """
        Fetches the forecasting information and translates it into a common Redis-ready nomenclature

        :param raw_forecast: The raw forecast for testing purpose. It is not advised to use the parameter productively.
        :return: The dictionary of forecasts following the common nomenclature. See the AbstractSourceAPI class for more
            information on the expected output format.
        """
        if raw_forecast is None:
            response: requests.Response = self.session.get(
                self.request_url,
                params = self.request_parameters
            )
            response.raise_for_status()
            raw_forecast = response.json()

        redis_forecast = self._transform_to_redis_format(raw_forecast)
        return redis_forecast

    def _transform_to_redis_format(self, raw_data: Dict) -> Dict[str, Any]:
        """
        Transforms the data to the common Redis representation
        """
        extractors = [
            jx.UnixTimeExtractor('measurement_time', 'unix_seconds[*]'),
            jx.PathExtractor('frequency', 'data[*]'),
        ]

        redis_data = dict(itertools.chain(*[ext.extract_information(raw_data).items() for ext in extractors]))

        return redis_data
