import pandas as pd
import pandera as pa
from src.models.schemas import PC6ProfileSchema
from src.models.cdf_schema import CDFSchema
from src.models.pc6_schema import PC6AggregatedSchema

def validate_profiles(df: pd.DataFrame, lazy: bool = False) -> pd.DataFrame:
    """
    Validate a DataFrame against the PC6ProfileSchema.
    
    Args:
        df (pd.DataFrame): The dataframe to validate.
        lazy (bool): If True, report all errors at once (Pandera lazy validation).
                     If False, fail on first error.
                     
    Returns:
        pd.DataFrame: The validated dataframe (coerced if schema mandates).
        
    Raises:
        pandera.errors.SchemaErrors: If validation fails and lazy=True.
        pandera.errors.SchemaError: If validation fails and lazy=False.
    """
    try:
        return PC6ProfileSchema.validate(df, lazy=lazy)
    except pa.errors.SchemaError as e:
        print(f"Validation Error: {e}")
        raise
    except pa.errors.SchemaErrors as e:
        print(f"Multiple Validation Errors:\n{e.failure_cases}")
        raise

def validate_cdf(df: pd.DataFrame, lazy: bool = False) -> pd.DataFrame:
    """
    Validate a DataFrame against the CDFSchema.
    
    Args:
        df (pd.DataFrame): The raw CDF dataframe.
        lazy (bool): Lazy validation flag.
        
    Returns:
        pd.DataFrame: Validated dataframe.
    """
    try:
        return CDFSchema.validate(df, lazy=lazy)
    except pa.errors.SchemaError as e:
        print(f"CDF Validation Error: {e}")
        raise
    except pa.errors.SchemaErrors as e:
        print(f"CDF Multiple Validation Errors:\n{e.failure_cases}")
        raise

def validate_pc6_aggregated(df: pd.DataFrame, lazy: bool = False) -> pd.DataFrame:
    """
    Validate a DataFrame against the PC6AggregatedSchema.
    
    Args:
        df (pd.DataFrame): Aggregated PC6 dataframe.
        
    Returns:
        pd.DataFrame: Validated dataframe.
    """
    try:
        return PC6AggregatedSchema.validate(df, lazy=lazy)
    except pa.errors.SchemaError as e:
        print(f"PC6 Validation Error: {e}")
        raise
    except pa.errors.SchemaErrors as e:
        print(f"PC6 Multiple Validation Errors:\n{e.failure_cases}")
        raise

