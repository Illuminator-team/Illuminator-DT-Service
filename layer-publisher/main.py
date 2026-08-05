# Updated main.py for PostGIS integration using latest p_forecast
import os, time, requests, sys, psycopg2

def required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value

# GeoServer config
REST = os.getenv("GEOSERVER_REST_URL", "http://geo:8080/geoserver/rest")
AUTH = (
    required_env("GEOSERVER_ADMIN_USER"),
    required_env("GEOSERVER_ADMIN_PASSWORD"),
)
WS = "rdp"
STORE = "pv_generation_data"
NAME = "solar_panel_layer"

# DB config
DB_CONN = {
    "host": os.getenv("POSTGRES_HOST", "timescale"),
    "port": int(os.getenv("POSTGRES_PORT", "5432")),
    "dbname": os.getenv("POSTGRES_DB", "rdp_db"),
    "user": required_env("POSTGRES_USER"),
    "password": required_env("POSTGRES_PASSWORD"),
}

# Logging helper
def log(*args):
    print("Args Printer Says:", *args)
    sys.stdout.flush()

def get_latest_p_forecast():
    """Fetch the latest p_forecast value from TimescaleDB for Illuminator"""
    conn = psycopg2.connect(**DB_CONN)
    cur = conn.cursor()
    cur.execute("""
        SELECT value
        FROM public.forecasts
        WHERE dp_id = (
            SELECT id 
            FROM data_points 
            WHERE name = 'p_forecast' AND data_provider = 'Illuminator'
        )
        ORDER BY fc_time DESC
        LIMIT 1;
    """)
    row = cur.fetchone()
    cur.close()
    conn.close()
    if row:
        log("Got the value!")
        return row[0]
    else:
        log("No p_forecast data found!")
        return None

def write_to_postgis(value: int):
    """Insert or update the latest forecast value into the PostGIS layer"""
    if value is None:
        log("Skipping PostGIS update: no value provided")
        return

    conn = psycopg2.connect(**DB_CONN)
    cur = conn.cursor()

    cur.execute("CREATE EXTENSION IF NOT EXISTS postgis;")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS solar_panel_layer (
            id SERIAL PRIMARY KEY,
            value FLOAT,
            geom GEOMETRY(Point, 4326)
        );
    """)

    # Fixed location of the solar panel
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
    log(f"Updated PostGIS with latest value: {value}")

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

def wait_for_geoserver(timeout=500):
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
    raise RuntimeError("GeoServer did not become ready in time.")

# ---------- one-time init ----------
wait_for_geoserver()
ensure_workspace()
ensure_store()
write_to_postgis(get_latest_p_forecast())
ensure_layer()
reload_geoserver()

# ---------- continuous updates ----------
while True:
    latest_value = get_latest_p_forecast()
    write_to_postgis(latest_value)
    reload_geoserver()
    time.sleep(10)
