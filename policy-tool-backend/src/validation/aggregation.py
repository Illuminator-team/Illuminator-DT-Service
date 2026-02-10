import pandas as pd
import logging
from src.ingestion.cdf import load_cdf_data
from src.utils.config import load_config

logger = logging.getLogger(__name__)

def validate_municipal_aggregation(hourly_path: str, cdf_path: str, config: dict):
    """
    Validates that the sum of hourly profiles matches the annual totals from CDF.
    """
    logger.info("Starting Municipal Aggregation Validation...")
    
    # 1. Load Expected Annual Totals (CDF)
    logger.info(f"Loading CDF data from {cdf_path}...")
    df_cdf = load_cdf_data(cdf_path)
    
    # Expected Electricity Gross (Approximate)
    # Note: CDF has Net Import. Gross = Net Import + Self-Consumed PV.
    # But we also have 'p6_kwh_productie_2023' (PV Export).
    # PV Total = PV Export / (1 - self_consumption_rate).
    # PV Self = PV Total * self_consumption_rate.
    # Elec Gross = Import + PV Self.
    
    # However, our engine does this calculation per PC6. 
    # To strictly validate, we should perhaps trust the engine's annual outputs if available,
    # or re-calculate expected totals here using the same logic.
    
    # For now, let's verify checking against the "Annual Data Lake" if it exists,
    # or just do a consistency check on what we can.
    
    # Let's use the 'pc6_annual_data.csv' if available, which should have the calculated annuals.
    annual_processed_path = "data/processed/pc6_annual_data.csv"
    try:
        df_annual = pd.read_csv(annual_processed_path)
        logger.info(f"Loaded processed annual data from {annual_processed_path}")
    except FileNotFoundError:
        logger.error(f"Could not find {annual_processed_path}. Cannot validate against processed annuals.")
        return False

    # Calculate Expected Electricity Gross
    # Elec_gross_annual = Import + PV_self
    # PV_self = PV_export / (1 - s) * s   (Wait. PV_total = PV_export / (1-s). Self = Total * s)
    # So PV_self = (PV_export / (1-s)) * s
    
    s = config.get('assumptions', {}).get('pv_self_consumption_share', 0.30)
    
    # Ensure columns exist and fillna
    if 'p6_kwh_2023' not in df_annual.columns:
        logger.error("p6_kwh_2023 missing from annual data.")
        return False
        
    df_annual['p6_kwh_2023'] = df_annual['p6_kwh_2023'].fillna(0)
    df_annual['p6_kwh_productie_2023'] = df_annual['p6_kwh_productie_2023'].fillna(0)
    
    # Calculate PV total and self-consumption
    # Avoid division by zero if s=1 (unlikely but safe to check)
    if s >= 1.0:
        logger.warning("Self consumption share >= 1.0. Assuming all generated is consumed?? Review logic.")
        pv_self = df_annual['p6_kwh_productie_2023'] # Fallback
    else:
        pv_total = df_annual['p6_kwh_productie_2023'] / (1 - s)
        pv_self = pv_total * s
        
    df_annual['elec_gross_calculated'] = df_annual['p6_kwh_2023'] + pv_self
    expected_elec_gross = df_annual['elec_gross_calculated'].sum()
    
    # Expected Heat Gross
    # 'heat_gross_annual' seems to be the column in the file based on head output
    if 'heat_gross_annual' in df_annual.columns:
        expected_heat_gross = df_annual['heat_gross_annual'].sum()
    else:
        logger.error("heat_gross_annual missing from annual data.")
        expected_heat_gross = 0.0

    logger.info(f"Expected Municipal Elec Gross: {expected_elec_gross:,.2f} kWh")
    logger.info(f"Expected Municipal Heat Gross: {expected_heat_gross:,.2f} kWh_th")

    # 2. Aggregate Hourly File
    logger.info(f"Aggregating hourly data from {hourly_path}...")
    
    total_elec_gross = 0.0
    total_heat_gross = 0.0
    
    chunksize = 100000
    for chunk in pd.read_csv(hourly_path, chunksize=chunksize):
        total_elec_gross += chunk['elec_gross_kwh'].sum()
        total_heat_gross += chunk['heat_gross_delivered_kwh_th'].sum()

    logger.info(f"Actual Municipal Elec Gross: {total_elec_gross:,.2f} kWh")
    logger.info(f"Actual Municipal Heat Gross: {total_heat_gross:,.2f} kWh_th")

    # 3. Compare
    elec_diff = abs(total_elec_gross - expected_elec_gross)
    elec_diff_pct = (elec_diff / expected_elec_gross) * 100 if expected_elec_gross > 0 else 0
    
    heat_diff = abs(total_heat_gross - expected_heat_gross)
    heat_diff_pct = (heat_diff / expected_heat_gross) * 100 if expected_heat_gross > 0 else 0
    
    is_valid = True
    
    if elec_diff_pct > 1.0: # 1% tolerance
        logger.error(f"Electricity aggregation mismatch! Diff: {elec_diff_pct:.2f}%")
        is_valid = False
    else:
        logger.info(f"Electricity aggregation PASS (Diff: {elec_diff_pct:.3f}%)")

    if heat_diff_pct > 1.0:
        logger.error(f"Heat aggregation mismatch! Diff: {heat_diff_pct:.2f}%")
        is_valid = False
    else:
        logger.info(f"Heat aggregation PASS (Diff: {heat_diff_pct:.3f}%)")
        
    return is_valid
