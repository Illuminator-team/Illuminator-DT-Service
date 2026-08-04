import pandas as pd
import logging
from typing import Dict, Any
from src.utils.config import load_config

logger = logging.getLogger(__name__)

def enrich_pc6_data(df: pd.DataFrame, electrification_fraction: float = 0.0) -> pd.DataFrame:
    """
    Enrich aggregated PC6 data with derived metrics.
    
    This function orchestrates:
    1. Estimation of missing annual data (if any).
    2. Climate normalization of gas consumption.
    3. Calculation of derived heat demand metrics (Gas vs Non-Gas).
    
    Args:
        df: Aggregated PC6 DataFrame.
        electrification_fraction: Fraction (0.0-1.0) of gas heat to shift to Heat Pumps.
        
    Returns:
        pd.DataFrame: Enriched DataFrame.
    """
    logger.info("Enriching PC6 data...")
    config = load_config()
    
    # 1. Estimate missing annual totals
    df = estimate_missing_data(df, config)
    
    # 2. Climate Normalization
    df = apply_climate_normalization(df, config)

    # 3. Calculate Heat Demand
    df = calculate_heat_demand(df, config, electrification_fraction)
        
    return df


def estimate_missing_data(df: pd.DataFrame, config: Dict[str, Any]) -> pd.DataFrame:
    """
    Fills missing annual data (gas/elec) with benchmark estimates based on floor area.
    """
    if 'oppervlakte' not in df.columns or 'residential_share' not in df.columns:
        return df

    bm = config['benchmarks']
    area = df['oppervlakte']
    res_share = df['residential_share']
    
    # --- Gas Estimate ---
    # Only estimate if column is missing OR if we have zero gas but non-zero connections.
    # IMPORTANT: If connections are explicitly 0, it's non-gas, so do NOT estimate gas.
    if 'p6_gasm3_2023' not in df.columns:
        df['p6_gasm3_2023'] = float('nan')
        
    # Check for gas connections (prefer explicit column)
    if 'p6_gas_aansluitingen_2023' in df.columns:
        has_gas_conns = df['p6_gas_aansluitingen_2023'] > 0
    else:
        has_gas_conns = df['gas_ean_count'] > 0
    
    # Identify rows where gas is missing but should likely exist (based on connections)
    is_missing_gas = df['p6_gasm3_2023'].isna() & has_gas_conns
    
    est_gas_benchmark = (
        (area * res_share * bm['residential_gas_m3_per_m2']) + 
        (area * (1 - res_share) * bm['non_residential_gas_m3_per_m2'])
    )
    
    if is_missing_gas.any():
        logger.info(f"Imputing missing gas data for {is_missing_gas.sum()} records based on benchmarks.")
        df.loc[is_missing_gas, 'p6_gasm3_2023'] = est_gas_benchmark

    # --- Electricity Estimate ---
    est_elec_benchmark = (
        (area * res_share * bm['residential_elec_kwh_per_m2']) + 
        (area * (1 - res_share) * bm['non_residential_elec_kwh_per_m2'])
    )
               
    if 'p6_kwh_2023' not in df.columns:
        df['p6_kwh_2023'] = float('nan')
        
    df['p6_kwh_2023'] = df['p6_kwh_2023'].fillna(est_elec_benchmark)
    
    return df


def apply_climate_normalization(df: pd.DataFrame, config: Dict[str, Any]) -> pd.DataFrame:
    """
    Applies climate normalization factor to gas consumption if enabled.
    """
    if 'p6_gasm3_2023' not in df.columns:
        return df
        
    # Store raw value for reference
    df['p6_gasm3_2023_raw'] = df['p6_gasm3_2023']
    
    norm_config = config.get('climate_normalization', {})
    if norm_config.get('enabled', False):
        factor = norm_config.get('factor_2023_to_average', 1.0)
        logger.info(f"Applying Climate Normalization to Gas Consumption (Factor: {factor})")
        df['p6_gasm3_2023'] = df['p6_gasm3_2023'] * factor
        df['climate_normalized'] = True
    else:
        df['climate_normalized'] = False
        
    return df


def calculate_heat_demand(df: pd.DataFrame, config: Dict[str, Any], electrification_fraction: float) -> pd.DataFrame:
    """
    Calculates derived heat demand metrics, including:
    - Gas-delivered heat (converted from m3)
    - Non-gas estimated heat (based on Option A or benchmarks)
    - Electrification shift (what-if scenario)
    """
    if 'p6_gasm3_2023' not in df.columns:
        # Return empty/zeroed columns if no gas data
        for col in ['gas_input_kwh_annual', 'heat_gas_delivered', 'heat_nongas_estimated', 'heat_gross_annual']:
            df[col] = 0.0
        return df

    kwh_per_m3 = config['physics']['kWh_per_m3_gas']
    eta_boiler = config['assumptions']['eta_boiler']
    bm = config['benchmarks']
    
    # --- A. Gas-based Heat ---
    df['gas_input_kwh_annual'] = df['p6_gasm3_2023'] * kwh_per_m3
    df['heat_gas_delivered'] = df['gas_input_kwh_annual'] * eta_boiler
    
    # --- B. Non-Gas Heat Estimate ---
    # 1. Determine Total Units and Gas Connections
    total_units = df['woningequivalent'].fillna(df['address_count']).fillna(1.0)
    total_units = total_units.replace(0, 1.0) # Avoid div/0
    
    gas_conns = df['p6_gas_aansluitingen_2023'].fillna(df['gas_ean_count']).fillna(0)
    
    # 2. Calculate Non-Gas Share
    # If gas_conns > total_units, clipped to 1.0 -> nongas = 0.0
    gas_share = (gas_conns / total_units).clip(upper=1.0)
    nongas_share = 1.0 - gas_share
    
    # 3. Estimate Heat for the Non-Gas portion
    heat_method = config.get('heat', {}).get('options', {}).get('nongas_estimation_method', 'benchmark')
    
    if heat_method == 'label_intensity' and 'heat_demand_label_based' in df.columns:
        # Option A: Use aggregated label-based heat potential
        # heat_demand_label_based = Sum(Area * Intensity) for all buildings in PC6
        # We attribute the non-gas share of this total to the non-gas systems (HP/District)
        logger.info("Using Label-Intensity method (Option A) for Non-Gas Heat estimation.")
        df['heat_nongas_estimated'] = df['heat_demand_label_based'] * nongas_share
    else:
        # Fallback to Benchmark
        if heat_method == 'label_intensity':
            logger.warning("Label intensity method requested but 'heat_demand_label_based' missing. Falling back to benchmark.")
            
        res_share = df['residential_share'].fillna(1.0)
        benchmark_m3_m2 = (
            (res_share * bm['residential_gas_m3_per_m2']) +
            ((1 - res_share) * bm['non_residential_gas_m3_per_m2'])
        )
        # Convert benchmark m3 to heat kWh
        df['heat_nongas_estimated'] = df['oppervlakte'] * nongas_share * benchmark_m3_m2 * kwh_per_m3 * eta_boiler

    # --- C. Electrification Scenario (Shift Gas -> HP) ---
    if electrification_fraction > 0:
        logger.info(f"Applying Electrification Scenario: shifting {electrification_fraction:.1%} of gas heat to Heat Pumps.")
        
        heat_gas_initial = df['heat_gas_delivered']
        shift_kwh = heat_gas_initial * electrification_fraction
        
        # 1. Reduce Gas Heat
        df['heat_gas_delivered'] = heat_gas_initial - shift_kwh
        
        # 2. Recalculate Gas Input (kWh fuel)
        df['gas_input_kwh_annual'] = df['heat_gas_delivered'] / eta_boiler
        
        # 3. Increase Non-Gas Heat (Heat Pump delivered heat)
        df['heat_nongas_estimated'] = df['heat_nongas_estimated'] + shift_kwh
        
    # --- D. Total Gross Heat ---
    df['heat_gross_annual'] = df['heat_gas_delivered'] + df['heat_nongas_estimated']
    
    # --- E. Current Electrification Share ---
    # Fraction of total heat demand met by non-gas sources (HP/District)
    # Handle division by zero
    df['current_electrification_share'] = df.apply(
        lambda row: row['heat_nongas_estimated'] / row['heat_gross_annual'] 
        if row['heat_gross_annual'] > 0 else 0.0, 
        axis=1
    )
    
    return df
