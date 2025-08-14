import os, json, time, requests, sys

# GeoServer config
REST = "http://geo:8080/geoserver/rest" # REST API endpoint, we don't use localhost because we are accessing it from the internal container network
AUTH = ("admin", "geoserver")
WS = "rdp"
STORE = "generation_data"
NAME = "solar_panel_data"
FNAME = f"{NAME}.json"
DATA_DIR = "/opt/geoserver/data_dir/data"  # Mounted volume from host

# Logging helper that flushes immediately
def log(*args):
    print("Args Printer Says:", *args)
    sys.stdout.flush()

def ensure_workspace():
    log(f"Creating workspace '{WS}'...")
    r = requests.post(f"{REST}/workspaces",
                      auth=AUTH, headers={"Content-Type": "text/xml"},
                      data=f"<workspace><name>{WS}</name></workspace>")
    log(f"Workspace status: {r.status_code}")

def ensure_store():
    log(f"Creating GeoJSON store '{STORE}'...")
    ds_xml = f"""
    <dataStore>
      <name>{STORE}</name>
      <connectionParameters>
        <entry key="file">file:data/{FNAME}</entry>
        <entry key="namespace">{WS}</entry>
      </connectionParameters>
    </dataStore>"""
    r = requests.post(f"{REST}/workspaces/{WS}/datastores",
                      auth=AUTH, headers={"Content-Type": "text/xml"}, data=ds_xml)
    log(f"Store status: {r.status_code}")
    log(r.text)

def ensure_layer():
    log(f"Creating layer '{NAME}'...")
    ft_xml = f"""
    <featureType>
      <name>{NAME}</name>
      <nativeName>{NAME}</nativeName>
      <srs>EPSG:4326</srs>
    </featureType>"""
    r = requests.post(f"{REST}/workspaces/{WS}/datastores/{STORE}/featuretypes",
                      auth=AUTH, headers={"Content-Type": "text/xml"}, data=ft_xml)
    log(f"Layer status: {r.status_code}")
    log(r.text)

def write_geojson(value: int):
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, FNAME)
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
    with open(path, "w") as f:
        json.dump(geojson, f)
    log(f"✔ Wrote GeoJSON: {path} with value {value}")

def reload_geoserver():
    log("Reloading GeoServer catalog...")
    r = requests.post(f"{REST}/reload", auth=AUTH)
    log(f"Reload status: {r.status_code}")

def wait_for_geoserver(timeout=60):
    log("--------- Waiting for GeoServer to be ready...")
    for i in range(timeout):
        try:
            r = requests.get(f"{REST}/about/version", auth=AUTH)
            if r.ok:
                log("GeoServer is ready!")
                return
            else:
                log(f"Still waiting... Status: {r.status_code}")
        except Exception as e:
            log(f">>>>>>>>> Attempt {i + 1}: {e}")
        time.sleep(1)
    raise RuntimeError("XXXXXXXXXXX GeoServer did not become ready in time.")

# ---------- one-time init ----------
wait_for_geoserver()
write_geojson(12345)
ensure_workspace()
ensure_store()
ensure_layer()
reload_geoserver()

# ---------- continuous updates ----------
value = 12346
while True:
    write_geojson(value)
    reload_geoserver()
    value += 1
    time.sleep(10)
