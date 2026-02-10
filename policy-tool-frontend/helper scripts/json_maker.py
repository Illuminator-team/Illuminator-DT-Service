from pathlib import Path
import pandas as pd

# Resolve project structure
HERE = Path(__file__).resolve()
PROJECT_ROOT = HERE.parent.parent
DATA_DIR = PROJECT_ROOT / "data"

# CSV file
csv_filename = DATA_DIR / "energiedata-match-gemeentecode=[GM0361].csv"

print(f"Reading {csv_filename}...")

# Reading with delimiter ';'
df = pd.read_csv(csv_filename, sep=';')

# 2. Define the specific columns you want for the PC6 tiles
pc6_columns = [
    'postcode',
    'pc6_gemiddelde_woz_waarde_woning',
    'pc6_eigendomssituatie_perc_koop',
    'pc6_eigendomssituatie_perc_huur',
    'pc6_eigendomssituatie_aantal_woningen_corporaties',
    'p6_grondbeslag_m2',
    'p6_gasm3_2023',
    'p6_gas_aansluitingen_2023',
    'p6_kwh_2023',
    'p6_kwh_productie_2023'
]

# 3. Create the lookup
# We take only the columns we need and remove duplicate rows 
# (since multiple addresses share the same postcode data)
pc6_lookup = df[pc6_columns].drop_duplicates(subset=['postcode'])

# 4. Clean up the postcode strings (remove spaces to ensure better matching)
# We keep the original postcode for display, but add a 'key' for matching
pc6_lookup['match_key'] = pc6_lookup['postcode'].str.replace(' ', '', regex=False)

# 5. Save to JSON
output_filename = DATA_DIR / 'pc6_lookup.json'
pc6_lookup.to_json(output_filename, orient='records', indent=4)

print(f"Success! Created {output_filename} with {len(pc6_lookup)} unique postcodes.")