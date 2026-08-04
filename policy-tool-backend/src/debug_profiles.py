from src.processing.profiles import get_normalized_profiles
import pandas as pd

try:
    profiles = get_normalized_profiles()
    print("Profiles Loaded:")
    print(profiles.head())
    print("Shape:", profiles.shape)
    print("NaN count:", profiles.isna().sum())
    print("G1 head:", profiles['G1'].head())
except Exception as e:
    print(e)
