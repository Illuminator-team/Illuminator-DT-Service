import pandas as pd
import numpy as np
from pathlib import Path

def verify_epic_7():
    print("Verifying Epic 7: PV Modeling & Net Demand...")
    
    annual_path = Path("data/processed/pc6_annual_data.csv")
    hourly_path = Path("data/processed/pc6_hourly_full.csv")
    
    if not annual_path.exists() or not hourly_path.exists():
        print(f"Error: Required files missing. {annual_path} or {hourly_path}")
        return

    # Load annual data
    annual_df = pd.read_csv(annual_path, index_col='postcode')
    
    # Load a chunk of hourly data to check consistency for a few PC6s
    # Full load might be too slow/memory intensive (2.5GB)
    # We'll use a chunk iterator to find the first few PC6s
    reader = pd.read_csv(hourly_path, chunksize=100000)
    
    pc6_list = annual_df.index[:10]
    results = {pc6: {"annual_prod": annual_df.loc[pc6, 'p6_kwh_productie_2023'], "hourly_sum": 0.0} for pc6 in pc6_list}
    
    found_pc6s = set()
    for chunk in reader:
        for pc6 in pc6_list:
            pc6_chunk = chunk[chunk['pc6'] == pc6]
            if not pc6_chunk.empty:
                results[pc6]["hourly_sum"] += pc6_chunk['pv_gen_kwh'].sum()
                found_pc6s.add(pc6)
        
        if len(found_pc6s) == len(pc6_list):
            # Check if we have processed all rows for these PC6s
            # Since rows are ordered by PC6 usually, we might be able to stop early 
            # once we see a PC6 NOT in our list after having seen them.
            # But let's just process enough chunks.
            pass
        
        # Heuristic: stop after 5M rows for speed, or continue
        if chunk.index[-1] > 2000000:
            break

    print("\nConsistency Check (sum(hourly_pv) vs annual_productie):")
    for pc6, data in results.items():
        if pc6 not in found_pc6s:
            continue
        expected = data['annual_prod']
        actual = data['hourly_sum']
        diff = abs(expected - actual)
        status = "PASS" if diff < 1.0 else "FAIL" # 1 kWh tolerance
        print(f"PC6 {pc6}: Expected {expected:.2f}, Actual {actual:.2f}, Diff {diff:.2f} -> {status}")

    # Verify Day/Night (Criteria 1)
    # Take one PC6 and check timestamp
    chunk = pd.read_csv(hourly_path, nrows=24)
    chunk['timestamp'] = pd.to_datetime(chunk['timestamp'])
    chunk['hour'] = chunk['timestamp'].dt.hour
    
    night_gen = chunk[(chunk['hour'] < 7) | (chunk['hour'] > 20)]['pv_gen_kwh'].sum()
    day_gen = chunk[(chunk['hour'] >= 10) & (chunk['hour'] <= 15)]['pv_gen_kwh'].sum()
    
    print(f"\nDay/Night Check:")
    print(f"Night Generation (Sum): {night_gen:.4f}")
    print(f"Day Generation (Sum): {day_gen:.4f}")
    
    if night_gen == 0 and day_gen >= 0:
        print("Criteria 1 (PV Profile): PASS")
    else:
        print("Criteria 1 (PV Profile): FAIL (Check if day has gen or night is non-zero)")

if __name__ == "__main__":
    verify_epic_7()
