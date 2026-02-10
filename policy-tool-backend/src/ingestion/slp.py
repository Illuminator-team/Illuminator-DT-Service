import pandas as pd
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

def load_slp_profiles(type: str, data_dir: str = "data/raw/slp") -> pd.DataFrame:
    """
    Load Standard Load Profiles.
    Handles NEDU multi-header CSV format.
    
    Args:
        type (str): 'electricity' or 'gas'.
        data_dir (str): Directory containing SLP files.
        
    Returns:
        pd.DataFrame: DataFrame with normalized hourly/quarter-hourly profiles.
    """
    path = Path(data_dir) / f"slp_{type}.csv"
    if not path.exists():
        raise FileNotFoundError(f"SLP file not found: {path}")
    
    logger.info(f"Loading SLP profiles for {type} from {path}...")
    
    # NEDU format details:
    # Electricity: 5 header rows, then CET;CEST, then ;van;tot, then data (Row 8)
    # Gas: 3 header rows, then blank?, then CET;CEST, then ;van;tot, then data (Row 7)
    
    # Heuristic: Find where numeric data starts by looking for date-like strings in first column
    # Or just skip a fixed amount and clean up.
    
    if type == 'electricity':
        # Header rows to extract column names
        header_df = pd.read_csv(path, sep=';', nrows=5, header=None)
        # Row 3 (index 2) is Categoriecode
        # Row 5 (index 4) is Richting (A/I)
        categories = header_df.iloc[2, 3:].dropna().values
        directions = header_df.iloc[4, 3:].dropna().values
        col_names = [f"{cat}_{dir}" for cat, dir in zip(categories, directions)]
        
        # Data starts at row 8 (skip 7)
        df = pd.read_csv(path, sep=';', skiprows=7, header=None)
        # First 3 columns are dates, rest are data
        # If there is a trailing separator, pandas might create an extra NaN column at the end
        data_cols = df.iloc[:, 3:]
        
        # Drop empty columns (all NaN) which might be caused by trailing separators
        data_cols = data_cols.dropna(axis=1, how='all')
        
        # Ensure length matches
        if len(data_cols.columns) == len(col_names):
            data_cols.columns = col_names
        else:
             # Fallback: just use first N columns
             logger.warning(f"Column count mismatch: Data {len(data_cols.columns)} vs Names {len(col_names)}. Truncating/Adjusting.")
             data_cols = data_cols.iloc[:, :len(col_names)]
             data_cols.columns = col_names
             
    else:
        # Gas
        header_df = pd.read_csv(path, sep=';', nrows=3, header=None)
        # Row 2 (index 1) is Code (G1A_TST, etc.)
        categories = header_df.iloc[1, 3:].values
        col_names = categories
        
        # Data starts at row 7 (skip 6)
        df = pd.read_csv(path, sep=';', skiprows=6, header=None)
        data_cols = df.iloc[:, 3:]
        data_cols.columns = col_names

    # Clean up: remove any completely empty columns (like 'LEEG' in gas)
    data_cols = data_cols.loc[:, ~data_cols.columns.str.contains('LEEG', na=False)]
    
    # Convert to numeric
    data_cols = data_cols.apply(pd.to_numeric, errors='coerce')
    
    # Drop rows with all NaN (if any at the end)
    data_cols = data_cols.dropna(how='all')

    logger.info(f"Successfully loaded {len(data_cols)} profile intervals for {type}.")
    
    # Normalize to sum=1.0 per column
    logger.info("Renormalizing profiles to sum=1.0...")
    data_cols = data_cols / data_cols.sum()
        
    return data_cols
