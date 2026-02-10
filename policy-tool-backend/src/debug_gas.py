from src.ingestion.slp import load_slp_profiles
import pandas as pd

try:
    df_gas = load_slp_profiles('gas')
    print("Gas Profiles Loaded:")
    print(df_gas.head())
    print(df_gas.tail())
    print("Columns:", df_gas.columns)
    print("NaN count:", df_gas.isna().sum().sum())
except Exception as e:
    print(e)
