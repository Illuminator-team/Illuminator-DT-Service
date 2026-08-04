import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)

def check_negatives(df: pd.DataFrame, columns: list[str]) -> dict:
    """
    Checks for negative values in specified columns.
    Returns a dictionary of columns with count of negative values.
    """
    results = {}
    for col in columns:
        if col in df.columns:
            neg_count = (df[col] < 0).sum()
            if neg_count > 0:
                results[col] = neg_count
                logger.warning(f"Column {col} has {neg_count} negative values.")
    return results

def check_peak_to_average(df: pd.DataFrame, column: str, threshold: float = 10.0) -> list[str]:
    """
    Checks if the peak-to-average ratio exceeds a threshold.
    Returns a list of PC6 identifiers (if index is PC6) or just logs it.
    
    Since the input df is likely a single PC6 profile (8760 rows), 
    we return True/False or raise specific warnings.
    """
    if column not in df.columns:
        return []
        
    mean_val = df[column].mean()
    max_val = df[column].max()
    
    if mean_val == 0:
        if max_val > 0:
             logger.warning(f"Column {column} has 0 mean but max {max_val}.")
        return []

    ratio = max_val / mean_val
    if ratio > threshold:
        logger.warning(f"Column {column} has high peak-to-average ratio: {ratio:.2f} (Threshold: {threshold})")
        return [f"Ratio: {ratio:.2f}"]
    
    return []

def validate_pc6_profile(df: pd.DataFrame, pc6_id: str) -> bool:
    """
    Runs all checks on a single PC6 profile DataFrame.
    """
    logger.info(f"Validating PC6 {pc6_id}...")
    is_valid = True
    
    # Check negatives
    cols_to_check = ['elec_gross_kwh', 'heat_gross_delivered_kwh_th']
    negatives = check_negatives(df, cols_to_check)
    if negatives:
        is_valid = False
        logger.error(f"PC6 {pc6_id} failed negative check: {negatives}")

    # Check peak ratios
    # Electricity
    elec_peak = check_peak_to_average(df, 'elec_gross_kwh', threshold=15.0) # Slightly higher tolerance
    if elec_peak:
        logger.warning(f"PC6 {pc6_id} electricity peak warning: {elec_peak}")
        
    # Heat
    heat_peak = check_peak_to_average(df, 'heat_gross_delivered_kwh_th', threshold=25.0) # Heat can be peaky
    if heat_peak:
         logger.warning(f"PC6 {pc6_id} heat peak warning: {heat_peak}")

    return is_valid
