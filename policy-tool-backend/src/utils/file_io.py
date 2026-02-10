import pandas as pd
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

def save_dataframe(df: pd.DataFrame, output_path: str, format: str = "csv"):
    """
    Save a dataframe to a file.
    
    Args:
        df (pd.DataFrame): The dataframe to save.
        output_path (str): The path to save to.
        format (str): 'csv' or 'parquet'.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"Saving dataframe to {path}...")
    
    if format == "csv":
        df.to_csv(path, index=False)
    elif format == "parquet":
        df.to_parquet(path, index=False)
    else:
        raise ValueError(f"Unsupported format: {format}")
        
    logger.info("Save complete.")
