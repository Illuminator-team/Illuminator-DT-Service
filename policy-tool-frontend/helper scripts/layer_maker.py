import pandas as pd
import geopandas as gpd
import requests
import numpy as np
from pathlib import Path

# Resolve paths
HERE = Path(__file__).resolve()
PROJECT_ROOT = HERE.parent.parent
DATA_DIR = PROJECT_ROOT / "data"

# 1. Load CSV
csv_path = DATA_DIR / "energiedata-match-gemeentecode=[GM0361].csv"

df = pd.read_csv(csv_path, sep=';')
df['pc_join'] = df['postcode'].str.replace(' ', '').str.upper()

def get_coords(pt):
    try:
        c = pt.replace('POINT (', '').replace(')', '').split()
        return float(c[0]), float(c[1])
    except: return None, None

df['lon'], df['lat'] = zip(*df['point'].map(get_coords))
df = df.dropna(subset=['lon', 'lat'])

# WHY AM I DOING THIS? pdok does not accept any sort of filtering based on pc6, gemeente code etc. It only respects bounding boxes with a limit below 1k,
# This means we have to split our bounding box to a grid and do multiple requests of ideally below 1k each. TODO look into this again.

# Setup the Grid based on CSV points
min_lon, max_lon = df['lon'].min() - 0.002, df['lon'].max() + 0.002
min_lat, max_lat = df['lat'].min() - 0.002, df['lat'].max() + 0.002

lon_steps = np.linspace(min_lon, max_lon, 6)
lat_steps = np.linspace(min_lat, max_lat, 6)

wfs_url = "https://service.pdok.nl/cbs/postcode6/2021/wfs/v1_0"
all_features = []

print(f"Scanning 25 precision cells for Alkmaar + De Rijp...")

for i in range(5):
    for j in range(5):
        c_min_lat, c_max_lat = lat_steps[i], lat_steps[i+1]
        c_min_lon, c_max_lon = lon_steps[j], lon_steps[j+1]
        
        # PDOK 2.0.0 order: minLat, minLon, maxLat, maxLon
        bbox_str = f"{c_min_lat},{c_min_lon},{c_max_lat},{c_max_lon},urn:ogc:def:crs:EPSG::4326"
        
        params = {
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typeNames": "postcode6:postcode6",
            "outputFormat": "application/json",
            "srsName": "urn:ogc:def:crs:EPSG::4326",
            "bbox": bbox_str,
            "count": 1000 
        }

        try:
            r = requests.get(wfs_url, params=params)
            data = r.json()
            features = data.get('features', [])
            all_features.extend(features)
            print(f"Cell [{i},{j}]: {len(features)} found.")
        except:
            continue

# 3. Final Merge & Diagnostic
if all_features:
    gdf_polygons = gpd.GeoDataFrame.from_features(all_features, crs="EPSG:4326")
    gdf_polygons = gdf_polygons.drop_duplicates(subset=['postcode6'])
    gdf_polygons['pc_join'] = gdf_polygons['postcode6'].str.replace(' ', '').str.upper()
    
    # Aggregate CSV
    pc6_stats = df.groupby('pc_join').agg({
        'p6_gasm3_2023': 'mean',
        'p6_kwh_2023': 'mean',
        'p6_kwh_productie_2023': 'mean'
    }).reset_index()

    final_gdf = gdf_polygons.merge(pc6_stats, on='pc_join', how='inner')
    
    # Find the "Lost Ones"
    missing = set(pc6_stats['pc_join']) - set(final_gdf['pc_join'])
    
    print(f"\n--- REPORT ---")
    print(f"Unique Postcodes in CSV: {len(pc6_stats)}")
    print(f"Total Polygons Caught:   {len(gdf_polygons)}")
    print(f"Successful Matches:      {len(final_gdf)}")
    print(f"Coverage Rate:            {len(final_gdf)/len(pc6_stats)*100:.1f}%")
    
    if missing:
        print(f"\nMissing {len(missing)} codes. First 10 missing: {list(missing)[:10]}")

    final_gdf.to_file(DATA_DIR / "alkmaar_energy_map.geojson", driver='GeoJSON')
    print("\nFile 'alkmaar_energy_map.geojson' is ready to use!")