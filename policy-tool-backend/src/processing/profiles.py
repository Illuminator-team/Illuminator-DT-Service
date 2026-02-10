import pandas as pd
import numpy as np
import logging
from src.ingestion.slp import load_slp_profiles
from src.utils.config import load_config

logger = logging.getLogger(__name__)

def get_normalized_profiles(temp_series: pd.Series = None) -> pd.DataFrame:
    """
    Get aligned, normalized profiles for the reference year.
    Returns a DataFrame with columns ['E1', 'E2', 'G1', 'G2'] and DateTimeIndex.
    """
    config = load_config()
    year = config['time']['reference_year']
    
    logger.info(f"Preparing profiles for year {year}...")
    
    # 1. Load raw
    df_elec = load_slp_profiles('electricity')
    df_gas = load_slp_profiles('gas')
    
    # 2. Electricity (15-min -> Hourly)
    if len(df_elec) > 10000:
        logger.info("Resampling electricity profiles from 15-min to hourly...")
        temp_index = pd.date_range(start=f"{year}-01-01", periods=len(df_elec), freq='15min')
        df_elec.index = temp_index
        df_elec = df_elec.resample('h').sum()
        
    # 3. Map/Aggregate Categories
    profiles = pd.DataFrame()
    
    # Electricity: Residential (E1*)
    e1_cols = [c for c in df_elec.columns if c.startswith('E1') and c.endswith('_A')]
    if e1_cols:
        profiles['E1'] = df_elec[e1_cols].mean(axis=1).values
    
    # Electricity: Commercial (E2*)
    e2_cols = [c for c in df_elec.columns if c.startswith('E2') and c.endswith('_A')]
    if e2_cols:
        profiles['E2'] = df_elec[e2_cols].mean(axis=1).values

    # 4. Gas / Heat Profile
    # If we have temperature, use Degree Hours (more realistic than flat SLP factors)
    if temp_series is not None:
        logger.info("Generating seasonal heat profile from temperature data...")
        t_base = 15.5 # Typical Dutch heating base temperature
        
        # Heating Degree Hours
        hdh = (t_base - temp_series).clip(lower=0)
        
        # Add DHW baseload (approx 15% of annual energy)
        # We assume DHW is constant or has a slight daily pattern, but constant is a good baseline.
        baseload_share = 0.15
        
        # Normalize HDH to sum to (1 - baseload_share)
        if hdh.sum() > 0:
            hdh_norm = (hdh / hdh.sum()) * (1.0 - baseload_share)
        else:
            hdh_norm = hdh # All zeros
            
        # Constant baseload (summing to baseload_share)
        baseload = pd.Series(baseload_share / 8760, index=hdh_norm.index)
        
        heat_profile = hdh_norm + baseload
        profiles['G1'] = heat_profile.values
        profiles['G2'] = heat_profile.values # Simplified: same shape for small business
        
    else:
        # Fallback to SLP factors (might be flat if misconfigured)
        logger.warning("No temperature series provided. Falling back to (potentially flat) gas SLP.")
        if 'G1A_TST' in df_gas.columns:
            profiles['G1'] = df_gas['G1A_TST'].values
        elif 'G1A' in df_gas.columns:
             profiles['G1'] = df_gas['G1A'].values
             
        if 'G2A_TST' in df_gas.columns:
            profiles['G2'] = df_gas['G2A_TST'].values
        elif 'G2A' in df_gas.columns:
            profiles['G2'] = df_gas['G2A'].values

    # Final Renormalization
    profiles = profiles / profiles.sum()
        
    # 5. Create Final Index (8760 hours)
    full_index = pd.date_range(start=f"{year}-01-01", periods=8760, freq='h')
    
    if len(profiles) > 8760:
        profiles = profiles.iloc[:8760]
    elif len(profiles) < 8760:
        profiles = profiles.reindex(range(8760)).fillna(0)
    
    profiles.index = full_index
    
    return profiles
