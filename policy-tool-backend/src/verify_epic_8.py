import pandas as pd
import numpy as np
from pathlib import Path

def verify_epic_8():
    print("Verifying Epic 8: Heat Demand (Gross)...")
    
    annual_path = Path("data/processed/pc6_annual_data.csv")
    hourly_path = Path("data/processed/pc6_hourly_full.csv")
    
    if not annual_path.exists() or not hourly_path.exists():
        print(f"Error: Required files missing. {annual_path} or {hourly_path}")
        return

    # Load annual data
    annual_df = pd.read_csv(annual_path, index_col='postcode')
    
    # Check if heat_gross_annual is populated
    if 'heat_gross_annual' not in annual_df.columns:
        print("FAIL: heat_gross_annual column missing in annual data.")
        return
    
    non_zero_heat = annual_df[annual_df['heat_gross_annual'] > 0]
    print(f"PC6s with non-zero heat: {len(non_zero_heat)} / {len(annual_df)}")
    
    # Load a chunk of hourly data
    reader = pd.read_csv(hourly_path, chunksize=100000)
    
    pc6_list = annual_df.index[:10]
    results = {pc6: {"annual_heat": annual_df.loc[pc6, 'heat_gross_annual'], "hourly_sum": 0.0} for pc6 in pc6_list}
    
    found_pc6s = set()
    for chunk in reader:
        for pc6 in pc6_list:
            pc6_chunk = chunk[chunk['pc6'] == pc6]
            if not pc6_chunk.empty:
                results[pc6]["hourly_sum"] += pc6_chunk['heat_gross_delivered_kwh_th'].sum()
                found_pc6s.add(pc6)
        
        if chunk.index[-1] > 2000000:
            break

    print("\nConsistency Check (sum(hourly_heat) vs annual_heat):")
    for pc6, data in results.items():
        if pc6 not in found_pc6s:
            continue
        expected = data['annual_heat']
        actual = data['hourly_sum']
        diff = abs(expected - actual)
        status = "PASS" if diff < 1.0 else "FAIL" 
        print(f"PC6 {pc6}: Expected {expected:.2f}, Actual {actual:.2f}, Diff {diff:.2f} -> {status}")

    # Verify column existence in output
    sample_chunk = pd.read_csv(hourly_path, nrows=1)
    if 'heat_gross_delivered_kwh_th' in sample_chunk.columns:
        print("\nCriteria (Data Model): PASS")
    else:
        print("\nCriteria (Data Model): FAIL (Column missing)")

if __name__ == "__main__":
    verify_epic_8()
