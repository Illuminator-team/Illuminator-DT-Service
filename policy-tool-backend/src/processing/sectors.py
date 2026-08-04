import pandas as pd
import logging

logger = logging.getLogger(__name__)

def assign_sector_weights(df: pd.DataFrame) -> pd.DataFrame:
    """
    Assign profile weights based on residential share.
    
    Args:
        df (pd.DataFrame): Aggregated PC6 dataframe (with residential_share).
        
    Returns:
        pd.DataFrame: Dataframe with added weight columns.
    """
    logger.info("Assigning sector weights...")
    
    if 'residential_share' not in df.columns:
        logger.warning("residential_share missing. Assuming 100% Residential fallback.")
        df['residential_share'] = 1.0
        
    # Weights for Electricity Profiles
    # E1A/E1B/E1C are Residential. E2A/E2B are Small Business.
    # We simplified: Use E1 for Residential part, E2 for Non-Res part.
    
    df['weight_res'] = df['residential_share']
    df['weight_nonres'] = 1.0 - df['residential_share']
    
    # Clip to 0-1 just in case
    df['weight_res'] = df['weight_res'].clip(0, 1)
    df['weight_nonres'] = df['weight_nonres'].clip(0, 1)
    
    # Explicit Profile Weights
    # E1 = Residential Electricity (E1A/B/C)
    # E2 = Commercial Electricity (E2A/B)
    df['weight_E1'] = df['weight_res']
    df['weight_E2'] = df['weight_nonres']
    
    # G1 = Residential Gas (G1A < 5000m3)
    # G2 = Commercial Gas (G2A > 5000m3 or just business type)
    # Assuming similar split for gas
    df['weight_G1'] = df['weight_res']
    df['weight_G2'] = df['weight_nonres']
    
    return df
