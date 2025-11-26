import ast
import pandas as pd

def convert_to_datetimeindex(
        data: str
    ) -> pd.DatetimeIndex:
    """
    Convert string of list of ISO 8601 datetime entries to pandas datetime index.
    """
    return pd.to_datetime(ast.literal_eval(data))

def convert_to_series(
        data: str,
        index: pd.DatetimeIndex
    ) -> pd.Series:
    """
    Convert string of list of data scalar entries to pandas series.
    """
    data_cleaned = data.replace('null', '0.0')
    data_as_list = ast.literal_eval(data_cleaned)
    return pd.Series(data_as_list, index=index)
