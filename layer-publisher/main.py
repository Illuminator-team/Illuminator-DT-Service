# Updated main.py for PostGIS integration
import os, time, requests, sys, psycopg2

# GeoServer config
REST = "http://geo:8080/geoserver/rest"
AUTH = ("admin", "geoserver")
WS = "rdp"
STORE = "pv_generation_data"
NAME = "solar_panel_layer"

# DB config
DB_CONN = {
    "host": "timescale",
    "port": 5432,
    "dbname": "rdp_db",
    "user": "postgres",
    "password": "iGj88603I4bd"
}

# Logging helper

def log(*args):
    print("Args Printer Says:", *args)
    sys.stdout.flush()

def write_to_postgis(value: int):
    conn = psycopg2.connect(**DB_CONN)
    cur = conn.cursor()

    cur.execute("CREATE EXTENSION IF NOT EXISTS postgis;")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS solar_panel_layer (
            id SERIAL PRIMARY KEY,
            value INTEGER,
            geom GEOMETRY(Point, 4326)
        );
    """)

    # Insert once or update later
    lon, lat = 4.3735, 52.0022

    cur.execute("""
        INSERT INTO solar_panel_layer (id, value, geom)
        VALUES (1, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326))
        ON CONFLICT (id)
        DO UPDATE SET value = EXCLUDED.value;
    """, (value, lon, lat))

    conn.commit()
    cur.close()
    conn.close()
    log(f" Updated value {value} into PostGIS")


# GeoServer setup
def ensure_workspace():
    log(f"Creating workspace '{WS}'...")
    r = requests.post(f"{REST}/workspaces",
                      auth=AUTH, headers={"Content-Type": "text/xml"},
                      data=f"<workspace><name>{WS}</name></workspace>")
    log(f"Workspace status: {r.status_code}")

def ensure_store():
    log(f"Creating PostGIS store '{STORE}'...")
    ds_xml = f"""
    <dataStore>
      <name>{STORE}</name>
      <connectionParameters>
        <entry key="host">{DB_CONN['host']}</entry>
        <entry key="port">{DB_CONN['port']}</entry>
        <entry key="database">{DB_CONN['dbname']}</entry>
        <entry key="user">{DB_CONN['user']}</entry>
        <entry key="passwd">{DB_CONN['password']}</entry>
        <entry key="dbtype">postgis</entry>
        <entry key="namespace">http://{WS}</entry>
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

def reload_geoserver():
    log("Reloading GeoServer catalog...")
    r = requests.post(f"{REST}/reload", auth=AUTH)
    log(f"Reload status: {r.status_code}")

def wait_for_geoserver(timeout=100):
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
ensure_workspace()
ensure_store()
write_to_postgis(12345)
ensure_layer()
reload_geoserver()

# ---------- continuous updates ----------
value = 12346
while True:
    write_to_postgis(value)
    reload_geoserver()
    value += 1
    time.sleep(10)
