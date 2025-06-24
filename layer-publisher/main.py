import requests
import json
import time

GEOSERVER_URL = "http://geo:8080/geoserver"
REST = f"{GEOSERVER_URL}/rest"
AUTH = ("admin", "geoserver")

WORKSPACE = "rdp"
DATASTORE = "sensor_data"
LAYER_NAME = "solar_panel_data"
FILENAME = "solar_panel_data.json"

def wait_for_geoserver():
    print("Waiting for GeoServer to become available...")
    for i in range(30):
        try:
            r = requests.get(f"{REST}/about/version", auth=AUTH)
            if r.ok:
                print("GeoServer is ready!")
                return
            else:
                print(f"Still waiting... Status: {r.status_code}")
        except Exception as e:
            print(f"⚠️  Attempt {i+1}: GeoServer not reachable ({e})")
        time.sleep(1)
    raise RuntimeError("GeoServer did not become ready after 30 seconds.")

def ensure_workspace_and_datastore():
    print("🔧 Ensuring workspace and datastore exist...")
    r = requests.post(
        f"{REST}/workspaces",
        auth=AUTH,
        headers={"Content-Type": "text/xml"},
        data=f"<workspace><name>{WORKSPACE}</name></workspace>"
    )
    if r.status_code not in (200, 201):
        print(f"Workspace creation: {r.status_code} {r.text}")

    ds_xml = f"""
    <dataStore>
      <name>{DATASTORE}</name>
      <connectionParameters>
        <entry key="url">file:data/{FILENAME}</entry>
      </connectionParameters>
    </dataStore>
    """
    r = requests.post(
        f"{REST}/workspaces/{WORKSPACE}/datastores",
        auth=AUTH,
        headers={"Content-Type": "text/xml"},
        data=ds_xml
    )
    if r.status_code not in (200, 201):
        print(f"Datastore creation: {r.status_code} {r.text}")

import os

def update_layer(value: int):
    local_dir = "/opt/geoserver/data_dir/data"  # this is inside the mounted volume
    os.makedirs(local_dir, exist_ok=True)

    local_path = os.path.join(local_dir, FILENAME)

    # Construct the GeoJSON
    geojson = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [4.373494941750751, 52.002189761571074]
            },
            "properties": {
                "value": value
            }
        }]
    }

    with open(local_path, "w") as f:
        json.dump(geojson, f)

    print(f"GeoJSON file written to {local_path}")

    # Instruct GeoServer to (re)read and publish
    upload_url = (
        f"{REST}/workspaces/{WORKSPACE}/datastores/{DATASTORE}/external.geojson?configure=all"
    )

    external_path = f"file:data/{FILENAME}"  # relative to GeoServer's data_dir
    
    r = requests.put(
        upload_url,
        auth=AUTH,
        headers={"Content-Type": "text/plain"},
        data=external_path
    )

    print(os.listdir(local_dir))


    if r.status_code in (200, 201):
        print(f"[{value}] GeoServer layer updated.")
    else:
        print(f"Upload failed ({r.status_code}): {r.text}")


# ------------------ MAIN LOOP ------------------
value = 12345

wait_for_geoserver()
update_layer(value)
ensure_workspace_and_datastore()

while True:
    update_layer(value)
    value += 1
    time.sleep(10)

