import pandas as pd
import logging
from src.utils.config import load_config
from src.utils.energy_labels import estimate_intensity

logger = logging.getLogger(__name__)

def aggregate_to_pc6(df: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate address-level data to PC6 level.
    """
    logger.info("Aggregating CDF/BAG data to PC6 level...")
    config = load_config()
    
    # Pre-calculation: Residential flag
    if 'gebruiksdoelen' in df.columns:
        df['is_residential'] = df['gebruiksdoelen'].str.contains('woonfunctie', case=False, na=False).astype(int)
    else:
        df['is_residential'] = 0
        
    # Pre-calculation: Label-based Heat Demand Potential (Option A)
    # Calculates potential heat demand for every building based on Area * Intensity(Label/Age)
    # This is "potential" because it applies to all buildings; we split gas/nongas later.
    if 'oppervlakte' in df.columns:
        # Using apply for now; could be vectorized if performance becomes an issue
        # We need to handle potential missing columns safely
        has_label = 'energieklasse' in df.columns
        has_year = 'pand_bouwjaar' in df.columns
        
        def calc_heat_potential(row):
            area = row['oppervlakte']
            if pd.isna(area): return 0.0
            
            label = row['energieklasse'] if has_label else None
            year = row['pand_bouwjaar'] if has_year else None
            is_res = bool(row['is_residential']) if 'is_residential' in row else True
            
            intensity = estimate_intensity(label, year, config, is_residential=is_res)
            return area * intensity

        logger.info("Calculating label-based heat potential per address...")
        df['heat_demand_label_based'] = df.apply(calc_heat_potential, axis=1)
    else:
        df['heat_demand_label_based'] = 0.0

    # PC6-level totals (repeated) -> First
    pc6_cols = [
        'p6_kwh_2023', 'p6_kwh_productie_2023', 'p6_gasm3_2023', 'p6_gas_aansluitingen_2023',
        'p6_grondbeslag_m2',
        'pc6_gemiddelde_woz_waarde_woning', 'pc6_eigendomssituatie_perc_koop',
        'pc6_eigendomssituatie_perc_huur', 'pc6_eigendomssituatie_aantal_woningen_corporaties',
        'buurtcode', 'wijkcode', 'gemeentecode'
    ]
    
    # Address-level attributes -> Sum
    sum_cols = ['oppervlakte', 'woningequivalent', 'gas_ean_count', 'heat_demand_label_based']
    
    agg_rules = {}
    for col in pc6_cols:
        if col in df.columns: agg_rules[col] = 'first'
    for col in sum_cols:
        if col in df.columns: agg_rules[col] = 'sum'
        
    agg_rules['is_residential'] = 'mean' # Fraction of addresses that are residential
    
    if not agg_rules:
        return pd.DataFrame()
    
    df_agg = df.groupby('postcode').agg(agg_rules)
    df_agg['address_count'] = df.groupby('postcode').size()
    
    df_agg = df_agg.rename(columns={'is_residential': 'residential_share'})
    
    logger.info(f"Aggregated {len(df)} addresses into {len(df_agg)} PC6 regions.")
    
    return df_agg
