import requests
import geopandas as gpd
import matplotlib.pyplot as plt
import contextily as cx  # adds OSM tiles under your data

import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

WFS_URL = "https://localhost/wfs"

response = requests.get(WFS_URL, verify=False)
geojson = response.json()


# 2. Load into a GeoDataFrame
gdf = gpd.GeoDataFrame.from_features(geojson["features"], crs="EPSG:4326")

# 3. Re-project to Web-Mercator (required for web basemaps)
gdf_web = gdf.to_crs(epsg=3857)

# 4. Plot
ax = gdf_web.plot(figsize=(8, 8), alpha=0.8, edgecolor="k")
cx.add_basemap(ax, source=cx.providers.OpenStreetMap.Mapnik)
ax.set_axis_off()
plt.tight_layout()
plt.savefig("wfs_static.png", dpi=180)
plt.show()

print("Static map saved as wfs_static.png")
