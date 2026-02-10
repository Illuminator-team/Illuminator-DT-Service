import pandas as pd
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

def load_cdf_data(file_path: str, target_gemeente: str = "GM0361") -> pd.DataFrame:
    """
    Load Common Data Factory CSV export.
    
    Args:
        file_path (str): Path to the CSV file.
        target_gemeente (str): Gemeentecode to filter for (default 'GM0361').
        
    Returns:
        pd.DataFrame: Loaded and filtered dataframe.
        
    Raises:
        FileNotFoundError: If file is missing.
        ValueError: If required columns are missing or filter returns empty.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"CDF file not found: {path}")
    
    logger.info(f"Loading CDF data from {path}...")
    
    # CDF exports are usually semicolon separated
    try:
        df = pd.read_csv(path, sep=';', dtype={'postcode': str, 'gemeentecode': str})
    except Exception as e:
        logger.error(f"Failed to read CSV: {e}")
        raise

    # Standardization (strip whitespace from columns)
    df.columns = [c.strip().lower() for c in df.columns]
    
    # Filter
    if 'gemeentecode' in df.columns:
        original_len = len(df)
        df = df[df['gemeentecode'] == target_gemeente].copy()
        logger.info(f"Filtered {original_len} rows to {len(df)} rows for {target_gemeente}.")
    else:
        logger.warning("Column 'gemeentecode' not found. Skipping filter.")
        
    if df.empty:
        logger.warning(f"No data found for {target_gemeente} in {file_path}.")
        return df

    # Impute missing PC6-level data
    df = impute_pc6_data(df)
        
    return df

def impute_pc6_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    For columns that are PC6-level metrics but may be missing (0) for some addresses,
    fill them with the value from other addresses in the same PC6.
    """
    pc6_cols = [
        'p6_kwh_2023', 'p6_kwh_productie_2023', 'p6_gasm3_2023', 'p6_gas_aansluitingen_2023', 
        'p6_grondbeslag_m2',
        'pc6_gemiddelde_woz_waarde_woning', 'pc6_eigendomssituatie_perc_koop', 
        'pc6_eigendomssituatie_perc_huur', 'pc6_eigendomssituatie_aantal_woningen_corporaties'
    ]
    
    logger.info("Imputing missing PC6-level data from neighboring addresses...")
    
    # We use postcode as the grouping key
    if 'postcode' not in df.columns:
        logger.warning("No 'postcode' column found, skipping imputation.")
        return df

    for col in pc6_cols:
        if col in df.columns:
            # For these metrics, if some addresses have a value and others have 0,
            # the non-zero value is the correct PC6-level value.
            # transform('max') efficiently propagates the non-zero value to all rows in the group.
            df[col] = df.groupby('postcode')[col].transform('max')
            
    return df
