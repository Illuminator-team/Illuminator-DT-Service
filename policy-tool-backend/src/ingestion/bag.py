import pandas as pd
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

def load_bag_data(file_path: str) -> pd.DataFrame:
    """
    Load Real BAG data (Open Data).
    Maps BAG columns to the internal schema expected by the pipeline.
    
    Args:
        file_path (str): Path to the BAG CSV.
        
    Returns:
        pd.DataFrame: Dataframe with 'postcode', 'oppervlakte', etc.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"BAG file not found: {path}")
    
    logger.info(f"Loading BAG data from {path}...")
    df = pd.read_csv(path)
    
    # Map BAG columns to internal schema
    # BAG: postcode, oppervlakte, gebruiksdoel
    # Target: postcode, oppervlakte, gebruiksdoelen, p6_kwh_2023 (NaN)
    
    df = df.rename(columns={
        'gebruiksdoel': 'gebruiksdoelen'
    })
    
    # Add missing energy columns as NaN (since we are using open data without energy readings)
    df['p6_kwh_2023'] = float('nan')
    df['p6_gasm3_2023'] = float('nan')
    df['p6_kwh_productie_2023'] = float('nan')
    df['p6_gas_aansluitingen_2023'] = float('nan')
    
    # Ensure postcode is PC6 (strip space already done in fetcher)
    
    # Fake gemeentecode for compatibility if needed
    df['gemeentecode'] = 'GM0361' 
    
    # Add pand_bouwjaar as NaN (missing in simple VBO fetch)
    df['pand_bouwjaar'] = float('nan')
    
    return df
