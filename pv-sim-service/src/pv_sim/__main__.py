import click
import json
import logging
import pathlib
import pyrdp_commons.cli
import redis

from .pv_system_sim import PVSystemSim
from .util import convert_to_datetimeindex, convert_to_series
from .weather_input import incomplete_forecast_reason

Logger = logging.getLogger('pv_sim')

def load_redis_connection_pool(redis_config: dict) -> redis.ConnectionPool:
    """
    Parses the configuration and instantiates the Redis connection pool
    """
    host = redis_config['host']
    port = redis_config['port']
    db = redis_config['db']
    pwd = redis_config.get('password')
    Logger.info(f'Configure redis connection to {host}:{port} using db {db}')

    if pwd:
        pool = redis.ConnectionPool(host=host, port=port, db=db, decode_responses=True, password=pwd)
    else:
        pool = redis.ConnectionPool(host=host, port=port, db=db, decode_responses=True)

    client = redis.Redis(connection_pool=pool)
    client.ping()  # Will raise an exception in case a connection error occurs
    Logger.info(f'Redis connection to {host}:{port} using db {db} is alive.')

    return pool

@click.command()
@click.option('-c', '--config', default='config.yml', help='config file path')
def main(config):
    # Read config file.
    config_file_path = pathlib.Path(config).resolve(strict=True)
    config = pyrdp_commons.cli.setup_app(config_file=str(config_file_path), env_file=None)

    # Redis config.
    redis_config = config['redis']
    redis_pool = load_redis_connection_pool(redis_config=redis_config)

    pv_sim_config = config['pv_sim']
    pv_sim = PVSystemSim(pv_sim_config)

    try:
        while True:
            with redis.StrictRedis(connection_pool=redis_pool) as r:
                weather_data_raw = r.xread(streams={pv_sim_config['input_stream']: '$'}, count=1, block=0)

            # Retrieve weather data.
            weather_data = weather_data_raw[0][1][-1][1]
            reason = incomplete_forecast_reason(weather_data)
            if reason is not None:
                Logger.warning(f"Skipping weather forecast {weather_data.get('forecast_time')}: {reason}")
                continue
            station = weather_data['station']
            forecast_time = weather_data['forecast_time']
            observation_time = convert_to_datetimeindex(weather_data['observation_time'])
            air_pressure = convert_to_series(weather_data['air_pressure'], observation_time)
            air_temperature_2m = convert_to_series(weather_data['air_temperature_2m'], observation_time)
            wind_speed_10m = convert_to_series(weather_data['wind_speed_10m'], observation_time)
            global_horizontal_irradiation = convert_to_series(weather_data['global_horizontal_irradiation'], observation_time)
            latitude = float(weather_data['latitude'])
            longitude = float(weather_data['longitude'])

            p_out, irrad_out, eta_out = pv_sim.simulate_power_output(
                observation_time, air_pressure, air_temperature_2m, wind_speed_10m, global_horizontal_irradiation, latitude, longitude
            )
            Logger.debug(f'Simulated PV power output has {len(p_out)} entries')
            Logger.debug(f'Simulated total in-plane irradiance has {len(irrad_out)} entries')
            Logger.debug(f'Simulated PV module efficiency has {len(eta_out)} entries')

            with redis.StrictRedis(connection_pool=redis_pool) as r:
                out = dict(
                    p_forecast=json.dumps(p_out.to_list()),
                    irrad_forecast=json.dumps(irrad_out.to_list()),
                    eta_forecast=json.dumps(eta_out.to_list()),
                    ts_forecast=json.dumps([ts.isoformat() for ts in p_out.index.to_list()]),
                    forecast_time=forecast_time,
                    data_provider='\"{}\"'.format('PVSystemSim'), # format as JSON string
                    location=station
                )
                r.xadd(pv_sim_config['output_stream'], out)
    except KeyboardInterrupt:
        Logger.info('Stopping PV sim service ...')
    finally:
        Logger.info('PV sim service stopped')

if __name__ == '__main__':
    main()
