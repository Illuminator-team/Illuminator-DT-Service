import numpy as np
import click
import json
import logging
import pathlib
import pyrdp_commons.cli
import redis

from pvlib.solarposition import get_solarposition
from pvlib.irradiance import erbs
from .pv_system_sim import PVSystemSim
from timezonefinder import TimezoneFinder
import pandas as pd
from .util import convert_to_datetimeindex, convert_to_series

from illuminator.engine import Simulation

import csv
import os

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

def calculate_PV_params(df, csv_out_file: str = '/app/output/solar_data_illuminator.csv'):

    # — same as before through step 6 —
    ghi = df['global_horizontal_irradiation']
    Ta  = df['air_temperature_2m']
    lat = float(df['latitude'].iat[0])
    lon = float(df['longitude'].iat[0])

    tf = TimezoneFinder()
    tz = tf.timezone_at(lat=lat, lng=lon)

    # build a tz-aware index
    times = pd.DatetimeIndex(df['time'])
    if times.tz is None:
        times = times.tz_localize(tz)
    else:
        times = times.tz_convert(tz)

    solpos    = get_solarposition(times, lat, lon)
    zenith    = solpos['zenith']
    azimuth   = solpos['azimuth']
    elevation = solpos['elevation']

    doy       = times.dayofyear.values
    erbs_res  = erbs(ghi.values, zenith.values, doy)
    dhi_array = erbs_res['dhi']
    dni_array = (ghi.values - dhi_array) / np.maximum(
        0.01,
        np.cos(np.radians(zenith.values))
    )

    # assemble DataFrame, including a Time column
    out = pd.DataFrame({
        'Time': times.strftime('%Y-%m-%d %H:%M:%S'),      # convert to '%Y-%m-%d %H:%M:%S'
        'G_Gh': ghi.values,
        'G_Dh': dhi_array,
        'G_Bn': dni_array,
        'Ta':   Ta.values,
        'hs':   elevation.values,
        'FF':   0.8,
        'Az':   azimuth.values
    }, index=df.index)

    with open(csv_out_file, 'w', newline='') as f:
        f.write('Solar_data\n')
        out.to_csv(f, index=False)
    return out


@click.command()
@click.option('-c', '--config', default='config.yml', help='config file path')
def main(config):

    csv_path = "/app/output/weather_data.csv"
    raw_jsonl_path = "/app/output/weather_data_raw.jsonl"
    header_written = os.path.exists(csv_path)  # avoid duplicate headers

    print('print: starting illuminator service ...')
    Logger.debug('Log: Starting illuminator service ...')
    # Read config file.
    config_file_path = pathlib.Path(config).resolve(strict=True)
    config = pyrdp_commons.cli.setup_app(config_file=str(config_file_path), env_file=None)

    # Redis config.
    redis_config = config['redis']
    redis_pool = load_redis_connection_pool(redis_config=redis_config)

    illuminator_config = config['illuminator_sim']

    try:
        while True:
            with redis.StrictRedis(connection_pool=redis_pool) as r:
                weather_data_raw = r.xread(streams={illuminator_config['input_stream']: '$'}, count=1, block=0)

            ## DUMP RAW DATA TO JSONL
            os.makedirs(os.path.dirname(raw_jsonl_path), exist_ok=True)
            with open(raw_jsonl_path, "a") as raw_f:
                # json.dumps on weather_data_raw, then newline
                raw_f.write(json.dumps(weather_data_raw))
                raw_f.write("\n")

            # Here, weather_data_raw is a list like: [(stream_name, [(id1, { …payload… }), …])]

            # Retrieve weather data.
            weather_data = weather_data_raw[0][1][-1][1]
            station = weather_data['station']
            forecast_time = weather_data['forecast_time']
            observation_time = convert_to_datetimeindex(weather_data['observation_time'])
            air_pressure = convert_to_series(weather_data['air_pressure'], observation_time)
            air_temperature_2m = convert_to_series(weather_data['air_temperature_2m'], observation_time)
            wind_speed_10m = convert_to_series(weather_data['wind_speed_10m'], observation_time)
            global_horizontal_irradiation = convert_to_series(weather_data['global_horizontal_irradiation'], observation_time)
            latitude = float(weather_data['latitude'])
            longitude = float(weather_data['longitude'])


            with open(csv_path, mode='w', newline='') as f:
                header_written = False
                # Flatten each time step into a row
                for ts in observation_time:
                    row = {
                        "time": ts.isoformat(),
                        "forecast_time": forecast_time,
                        "station": station,
                        "air_pressure": air_pressure[ts],
                        "air_temperature_2m": air_temperature_2m[ts],
                        "wind_speed_10m": wind_speed_10m[ts],
                        "global_horizontal_irradiation": global_horizontal_irradiation[ts],
                        "latitude": latitude,
                        "longitude": longitude
                    }
                    # Write to CSV
                    writer = csv.DictWriter(f, fieldnames=row.keys())
                    if not header_written:
                        f.write('weather_forecast\n')
                        writer.writeheader()
                        header_written = True
                    writer.writerow(row)

                
            data = pd.read_csv(csv_path, skiprows=1, delimiter=',')
            params = calculate_PV_params(data, csv_out_file='/app/output/solar_data_illuminator.csv')
            start_time = params['Time'].min()
            end_time = params['Time'].max()
            print(f'Start time: {start_time}, End time: {end_time}')

            simulation = Simulation('/app/output/pv.yaml')
            simulation.set_scenario_param('time_resolution', 3600)  # 1 hour in seconds
            simulation.set_scenario_param('start_time', start_time)
            simulation.set_scenario_param('end_time', end_time)
            simulation.set_model_param(model_name='CSV_pv', parameter='file_path', value='/app/output/solar_data_illuminator.csv')
            simulation.set_monitor_param(parameter='file', value='/app/output/illuminator_output.csv')

            # run the simulation
            simulation.run()

            df = pd.read_csv('/app/output/illuminator_output.csv', delimiter=',')

            # Extract the 'PV1.pv_gen' column as a list
            p_forecast = df['PV1.pv_gen']
            p_forecast.index = pd.to_datetime(df['date'])


            print('logging')
            Logger.debug(f'weather_data type: {type(weather_data)}')
            Logger.debug(f'forecast_time type: {type(forecast_time)}')
            Logger.debug(f'observation_time type: {type(observation_time)}')
            Logger.debug(f'air_temperature_2m type: {type(air_temperature_2m)}')
            Logger.debug(f'global_horizontal_irradiation type: {type(global_horizontal_irradiation)}')

            with redis.StrictRedis(connection_pool=redis_pool) as r:
                out = dict(
                    p_forecast=json.dumps(p_forecast.tolist()),
                    ts_forecast=json.dumps([ts.isoformat() for ts in p_forecast.index.to_list()]),
                    forecast_time=forecast_time,
                    data_provider='\"{}\"'.format('Illuminator'), # format as JSON string
                    location=station
                )
                r.xadd(illuminator_config['output_stream'], out)
    except KeyboardInterrupt:
        Logger.info('Stopping PV sim service ...')
    finally:
        Logger.info('PV sim service stopped')

if __name__ == '__main__':
    print('print: starting illuminator main ...')
    Logger.debug('Log: Starting illuminator main ...')
    main()
