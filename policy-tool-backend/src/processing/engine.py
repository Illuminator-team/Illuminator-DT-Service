import pandas as pd
import logging
from typing import Iterator

from src.utils.config import load_config

logger = logging.getLogger(__name__)

def generate_hourly_profiles(pc6_df: pd.DataFrame, slp_df: pd.DataFrame, pv_profile: pd.Series = None) -> Iterator[pd.DataFrame]:
    """
    Generate hourly demand profiles for each PC6.
    
    Args:
        pc6_df (pd.DataFrame): Enriched PC6 data.
        slp_df (pd.DataFrame): SLP profiles.
        pv_profile (pd.Series): Normalized PV generation profile (kWh/kWp). 
                                If None, PV generation is 0.
        
    Yields:
        pd.DataFrame: Hourly dataframe for one PC6.
    """
    logger.info(f"Generating hourly profiles for {len(pc6_df)} regions...")
    
    # Load Config for assumptions
    config = load_config()
    cop = config['assumptions'].get('default_cop', 3.0)
    pv_self_share = config['assumptions'].get('pv_self_consumption_share', 0.30)
    
    # Calculate Annual Yield from profile if available
    pv_yield = pv_profile.sum() if pv_profile is not None else 1.0
    if pv_yield == 0: pv_yield = 1.0 # Avoid div/0
    
    # Iterate through PC6s
    for pc6, row in pc6_df.iterrows():
        # Electricity Gross
        # Elec_gross_annual = Elec_import_annual + PV_self_annual
        elec_import_annual = row['p6_kwh_2023']
        pv_self_annual = 0.0
        
        if 'p6_kwh_productie_2023' in row and pd.notna(row['p6_kwh_productie_2023']):
            pv_export_annual = row['p6_kwh_productie_2023']
            if pv_self_share < 1.0:
                pv_total_annual = pv_export_annual / (1.0 - pv_self_share)
                pv_self_annual = pv_total_annual * pv_self_share
        
        elec_gross_annual = elec_import_annual + pv_self_annual
        elec_shape = (row['weight_E1'] * slp_df['E1']) + (row['weight_E2'] * slp_df['E2'])
        elec_gross = elec_gross_annual * elec_shape
        
        # Heat Gross
        heat_annual = row['heat_gross_annual']
        heat_shape = (row['weight_G1'] * slp_df['G1']) + (row['weight_G2'] * slp_df['G2'])
        heat_gross = heat_annual * heat_shape
        
        # PV Generation
        pv_gen = 0.0
        if pv_profile is not None and 'p6_kwh_productie_2023' in row:
            annual_prod = row['p6_kwh_productie_2023']
            if pd.notna(annual_prod) and annual_prod > 0:
                capacity_kwp = annual_prod / pv_yield
                pv_gen = capacity_kwp * pv_profile.values
        
        # Net Electricity Demand & Grid
        elec_net = elec_gross.values - pv_gen
        grid_import = pd.Series(elec_net).clip(lower=0).values
        grid_export = pd.Series(-elec_net).clip(lower=0).values
        
        # Net Heat Demand (Gas vs Elec Input)
        # Gas Input (only for gas-heated portion)
        # Note: heat_gas_delivered is the annual portion. 
        # gas_input_annual = heat_gas_delivered / eta_boiler (done in enrichment)
        gas_annual = row.get('gas_input_kwh_annual', 0.0)
        gas_input_hourly = gas_annual * heat_shape.values
        
        # HP Elec Input (only for nongas portion)
        # heat_nongas_estimated is the annual portion.
        # Elec_input = heat_delivered / COP
        heat_nongas_annual = row.get('heat_nongas_estimated', 0.0)
        heat_nongas_hourly = heat_nongas_annual * heat_shape.values
        hp_elec_input_hourly = heat_nongas_hourly / cop
        
        # Total Net Heat External Input (Gas + HP Elec)
        heat_net_external = gas_input_hourly + hp_elec_input_hourly
        
        # Create Result DF for this PC6
        df_pc6 = pd.DataFrame({
            "pc6": pc6,
            "timestamp": slp_df.index,
            "elec_gross_kwh": elec_gross.values,
            "heat_gross_delivered_kwh_th": heat_gross.values,
            "pv_gen_kwh": pv_gen,
            "elec_net_kwh": elec_net,
            "grid_import_kwh": grid_import,
            "grid_export_kwh": grid_export,
            "hp_elec_input_kwh": hp_elec_input_hourly,
            "gas_input_kwh": gas_input_hourly,
            "heat_net_external_input_kwh": heat_net_external
        })
        
        yield df_pc6
