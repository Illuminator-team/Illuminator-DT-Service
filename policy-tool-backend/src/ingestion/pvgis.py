import pandas as pd
import requests
import logging
from io import StringIO

logger = logging.getLogger(__name__)

def fetch_pvgis_hourly(lat: float, lon: float, peakpower: float = 1.0, loss: float = 14) -> tuple[pd.Series, pd.Series]:
    """
    Fetch hourly PV generation and temperature data from JRC PVGIS API (seriescalc).
    Uses 2019 as a representative year.
    
    Args:
        lat (float): Latitude.
        lon (float): Longitude.
        peakpower (float): Installed capacity in kWp.
        loss (float): System loss in %.
        
    Returns:
        tuple[pd.Series, pd.Series]: (PV output in kW, Temperature in degC)
    """
    # Use seriescalc for hourly time series
    url = "https://re.jrc.ec.europa.eu/api/v5_2/seriescalc"
    params = {
        'lat': lat,
        'lon': lon,
        'peakpower': peakpower,
        'loss': loss,
        'outputformat': 'json',
        'startyear': 2019,
        'endyear': 2019,
        'pvcalculation': 1,
        'components': 1 # Includes temperature
    }
    
    logger.info(f"Fetching PVGIS data for {lat}, {lon} (Year 2019)...")
    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        if 'outputs' not in data or 'hourly' not in data['outputs']:
             raise ValueError(f"Unexpected PVGIS response structure: {data.keys()}")
             
        hourly_data = data['outputs']['hourly']
        df = pd.DataFrame(hourly_data)
        
        # 'P' is power in W. We want kW.
        # 'T2m' is air temperature at 2m
        if 'P' not in df.columns or 'T2m' not in df.columns:
             raise ValueError(f"Required columns ('P' or 'T2m') missing from PVGIS response. Found: {df.columns}")
             
        pv_series = df['P'] / 1000.0
        temp_series = df['T2m']
        
        # Ensure 8760
        if len(pv_series) > 8760:
            pv_series = pv_series.iloc[:8760]
            temp_series = temp_series.iloc[:8760]
        elif len(pv_series) < 8760:
            pv_series = pv_series.reindex(range(8760), fill_value=0)
            temp_series = temp_series.reindex(range(8760), fill_value=temp_series.mean())
            
        logger.info(f"Fetched {len(pv_series)} hourly points. Total yield: {pv_series.sum():.2f} kWh/kWp")
        return pv_series.reset_index(drop=True), temp_series.reset_index(drop=True)
        
    except Exception as e:
        logger.error(f"Failed to fetch PVGIS data: {e}")
        raise
