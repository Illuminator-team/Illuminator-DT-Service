import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import psycopg2
import requests
from consumption import (
    ConsumptionArtifact,
    fetch_consumption_artifact,
    get_consumption_readiness_signature,
)
from ev import EvArtifact, fetch_ev_artifact, get_ev_readiness_signature
from ev_postgis import sync_ev_layer
from grid import GridArtifact, fetch_grid_artifact, get_grid_readiness_signature
from grid_postgis import sync_grid_layer
from model_postgis import sync_model_layer
from pc6 import Pc6Record, get_layer_config, load_manifest, load_pc6_records
from postgis_sql import values_template
from publication_scope import parse_publish_models
from psycopg2.extras import execute_values
from pv import (
    PV_PROPERTY_FIELDS,
    PvArtifact,
    PvCapacityRecord,
    fetch_pv_artifact,
    get_pv_readiness_signature,
)
from wind import WindArtifact, fetch_wind_artifact, get_wind_readiness_signature
from wind_postgis import sync_wind_layer
from heat import (
    HEAT_LAYER_IDS,
    HeatArtifact,
    fetch_heat_artifact,
    get_heat_readiness_signature,
)
from heat_postgis import sync_heat_layers

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
)
LOGGER = logging.getLogger("layer-publisher")


def required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def bbox_env(name: str, default: list[float]) -> list[float]:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        values = [float(item.strip()) for item in raw.split(",")]
    except ValueError as exc:
        raise RuntimeError(f"{name} must contain four comma-separated numbers") from exc
    if len(values) != 4:
        raise RuntimeError(f"{name} must contain four comma-separated numbers")
    return values


MANIFEST_PATH = Path(os.getenv("PUBLISHER_MANIFEST_PATH", "/app/layer-manifest.json"))
MANIFEST = load_manifest(MANIFEST_PATH)
PC6_CONFIG = get_layer_config(MANIFEST, "layer:policy-tool:pc6-energy")
PV_CONFIG = get_layer_config(MANIFEST, "layer:pv-map:capacity")
GRID_LINES_CONFIG = get_layer_config(MANIFEST, "layer:grid-model:lines")
GRID_TRANSFORMERS_CONFIG = get_layer_config(
    MANIFEST, "layer:grid-model:transformers"
)
GRID_LV_MV_REACH_CONFIG = get_layer_config(
    MANIFEST, "layer:grid-model:lv-mv-transformer-reach"
)
GRID_MV_HV_REACH_CONFIG = get_layer_config(
    MANIFEST, "layer:grid-model:mv-hv-transformer-reach"
)
GRID_CONFIGS = {
    "grid_lines": GRID_LINES_CONFIG,
    "grid_transformers": GRID_TRANSFORMERS_CONFIG,
    "grid_lv_mv_transformer_reach": GRID_LV_MV_REACH_CONFIG,
    "grid_mv_hv_transformer_reach": GRID_MV_HV_REACH_CONFIG,
}
WIND_CONFIG = get_layer_config(MANIFEST, "layer:wind-turbine-map:public-turbines")
HEAT_CONFIGS = {
    layer_id: get_layer_config(MANIFEST, f"layer:heat-net-map:{layer_id}")
    for layer_id in HEAT_LAYER_IDS
}
EV_CONFIG = get_layer_config(MANIFEST, "layer:ev-map:public-chargers")
CONSUMPTION_CONFIG = get_layer_config(
    MANIFEST, "layer:consumption-map:electricity-areas"
)
PC6_SOURCE_PATH = Path(os.getenv("PC6_SOURCE_PATH", PC6_CONFIG["source"]["path"]))
PV_API_URL = os.getenv("PV_API_URL", PV_CONFIG["source"]["base_url"]).rstrip("/")
PV_EXPECTED_RELEASE_COMMIT = os.getenv(
    "PV_EXPECTED_RELEASE_COMMIT", PV_CONFIG["source"]["release_commit"]
)
PV_EXPECTED_CONTAINER_IMAGE = os.getenv(
    "PV_EXPECTED_CONTAINER_IMAGE", PV_CONFIG["source"]["container_image"]
)
GRID_API_URL = os.getenv(
    "GRID_API_URL", GRID_LINES_CONFIG["source"]["base_url"]
).rstrip("/")
GRID_EXPECTED_RELEASE_COMMIT = os.getenv(
    "GRID_EXPECTED_RELEASE_COMMIT", GRID_LINES_CONFIG["source"]["release_commit"]
)
GRID_EXPECTED_CONTAINER_DIGEST = os.getenv(
    "GRID_EXPECTED_CONTAINER_DIGEST",
    GRID_LINES_CONFIG["source"]["container_digest"],
)
GRID_EXPECTED_DATA_MODE = os.getenv("GRID_EXPECTED_DATA_MODE", "real_source")
GRID_EXPORT_BBOX = bbox_env(
    "GRID_EXPORT_BBOX",
    GRID_LINES_CONFIG["source"]["production_selection"]["bbox"],
)
WIND_API_URL = os.getenv(
    "WIND_API_URL", WIND_CONFIG["source"]["base_url"]
).rstrip("/")
WIND_EXPECTED_RELEASE_COMMIT = os.getenv(
    "WIND_EXPECTED_RELEASE_COMMIT", WIND_CONFIG["source"]["release_commit"]
)
WIND_EXPECTED_CONTAINER_IMAGE = os.getenv(
    "WIND_EXPECTED_CONTAINER_IMAGE",
    WIND_CONFIG["source"]["container_reported_identity"],
)
WIND_EXPECTED_CONTAINER_DIGEST = os.getenv(
    "WIND_EXPECTED_CONTAINER_DIGEST", WIND_CONFIG["source"]["container_digest"]
)
WIND_EXPECTED_DATA_MODE = os.getenv("WIND_EXPECTED_DATA_MODE", "real_source")
HEAT_API_URL = os.getenv(
    "HEAT_API_URL", next(iter(HEAT_CONFIGS.values()))["source"]["base_url"]
).rstrip("/")
HEAT_EXPECTED_RELEASE_COMMIT = os.getenv(
    "HEAT_EXPECTED_RELEASE_COMMIT",
    next(iter(HEAT_CONFIGS.values()))["source"]["release_commit"],
)
HEAT_EXPECTED_CONTAINER_DIGEST = os.getenv(
    "HEAT_EXPECTED_CONTAINER_DIGEST",
    next(iter(HEAT_CONFIGS.values()))["source"]["container_digest"],
)
HEAT_EXPECTED_DATA_MODE = os.getenv("HEAT_EXPECTED_DATA_MODE", "real_source")
EV_API_URL = os.getenv("EV_API_URL", EV_CONFIG["source"]["base_url"]).rstrip("/")
EV_EXPECTED_RELEASE_COMMIT = os.getenv(
    "EV_EXPECTED_RELEASE_COMMIT", EV_CONFIG["source"]["release_commit"]
)
EV_EXPECTED_CONTAINER_IMAGE = os.getenv(
    "EV_EXPECTED_CONTAINER_IMAGE", EV_CONFIG["source"]["container_image"]
)
CONSUMPTION_API_URL = os.getenv(
    "CONSUMPTION_API_URL", CONSUMPTION_CONFIG["source"]["base_url"]
).rstrip("/")
CONSUMPTION_EXPECTED_RELEASE_COMMIT = os.getenv(
    "CONSUMPTION_EXPECTED_RELEASE_COMMIT",
    CONSUMPTION_CONFIG["source"]["release_commit"],
)
CONSUMPTION_EXPECTED_CONTAINER_IMAGE = os.getenv(
    "CONSUMPTION_EXPECTED_CONTAINER_IMAGE",
    CONSUMPTION_CONFIG["source"]["container_image"],
)

GEOSERVER_REST_URL = os.getenv(
    "GEOSERVER_REST_URL", "http://geo:8080/geoserver/rest"
).rstrip("/")
GEOSERVER_AUTH = (
    required_env("GEOSERVER_ADMIN_USER"),
    required_env("GEOSERVER_ADMIN_PASSWORD"),
)
WORKSPACE = os.getenv("GEOSERVER_WORKSPACE", MANIFEST["workspace"])
DATASTORE = os.getenv("GEOSERVER_DATASTORE", MANIFEST["datastore"])
PUBLISH_INTERVAL_SECONDS = int(os.getenv("PUBLISH_INTERVAL_SECONDS", "10"))
PUBLISH_ONCE = os.getenv("PUBLISH_ONCE", "false").lower() == "true"
GEOSERVER_REQUEST_TIMEOUT_SECONDS = int(
    os.getenv("GEOSERVER_REQUEST_TIMEOUT_SECONDS", "90")
)

DB_CONN = {
    "host": os.getenv("POSTGRES_HOST", "timescale"),
    "port": int(os.getenv("POSTGRES_PORT", "5432")),
    "dbname": os.getenv("POSTGRES_DB", "rdp_db"),
    "user": required_env("POSTGRES_USER"),
    "password": required_env("POSTGRES_PASSWORD"),
}

PC6_TABLE = PC6_CONFIG["table"]
PC6_LAYER = PC6_CONFIG["geoserver_layer"]
PV_TABLE = PV_CONFIG["table"]
PV_LAYER = PV_CONFIG["geoserver_layer"]
GRID_TABLES = {
    layer_id: config["table"] for layer_id, config in GRID_CONFIGS.items()
}
WIND_TABLE = WIND_CONFIG["table"]
WIND_LAYER = WIND_CONFIG["geoserver_layer"]
HEAT_TABLES = {
    layer_id: config["table"] for layer_id, config in HEAT_CONFIGS.items()
}
EV_TABLE = EV_CONFIG["table"]
EV_LAYER = EV_CONFIG["geoserver_layer"]
CONSUMPTION_TABLE = CONSUMPTION_CONFIG["table"]
CONSUMPTION_LAYER = CONSUMPTION_CONFIG["geoserver_layer"]
SOLAR_TABLE = "solar_panel_layer"
SOLAR_LAYER = "solar_panel_layer"

PV_SQL_TYPES = {
    "feature_id": "TEXT PRIMARY KEY",
    "feature_uri": "TEXT UNIQUE NOT NULL",
    "source_feature_id": "TEXT NOT NULL",
    "cbs_buurt_code": "TEXT UNIQUE NOT NULL",
    "buurt_name": "TEXT NOT NULL",
    "municipality": "TEXT NOT NULL",
    "pv_capacity_kwp": "DOUBLE PRECISION NOT NULL CHECK (pv_capacity_kwp >= 0)",
    "pv_capacity_mwp": "DOUBLE PRECISION NOT NULL CHECK (pv_capacity_mwp >= 0)",
    "residential_kwp_real": "DOUBLE PRECISION NOT NULL CHECK (residential_kwp_real >= 0)",
    "commercial_kwp_derived": "DOUBLE PRECISION NOT NULL CHECK (commercial_kwp_derived >= 0)",
    "capacity_kwp_combined": "DOUBLE PRECISION NOT NULL CHECK (capacity_kwp_combined >= 0)",
    "capacity_method": "TEXT NOT NULL",
    "unit": "TEXT NOT NULL",
    "residential_input_status": "TEXT NOT NULL",
    "datacompleetheid": "SMALLINT NOT NULL CHECK (datacompleetheid BETWEEN 0 AND 3)",
    "datacompleetheid_label": "TEXT NOT NULL",
    "datacompleetheid_method_version": "TEXT NOT NULL",
    "datacompleetheid_assessed_at": "TIMESTAMPTZ NOT NULL",
    "datacompleetheid_observed": "TEXT NOT NULL",
    "datacompleetheid_estimated": "TEXT NOT NULL",
    "datacompleetheid_assumed": "TEXT NOT NULL",
    "datacompleetheid_missing": "TEXT NOT NULL",
    "completeness_reason": "TEXT NOT NULL",
    "source_name": "TEXT NOT NULL",
    "source_reference_period": "TEXT NOT NULL",
    "source_modified_at": "TIMESTAMPTZ",
    "source_retrieved_at": "TIMESTAMPTZ",
    "source_last_updated": "TIMESTAMPTZ",
    "model_run_at": "TIMESTAMPTZ NOT NULL",
    "output_generated_at": "TIMESTAMPTZ NOT NULL",
    "last_updated": "TIMESTAMPTZ NOT NULL",
    "model_version": "TEXT NOT NULL",
    "metadata_contract_version": "TEXT NOT NULL",
}


def wait_for_postgres(attempts: int = 180) -> None:
    for attempt in range(1, attempts + 1):
        try:
            with psycopg2.connect(**DB_CONN):
                LOGGER.info("Postgres is ready")
                return
        except psycopg2.Error as exc:
            if attempt == attempts:
                raise RuntimeError("Postgres did not become ready") from exc
            if attempt == 1 or attempt % 10 == 0:
                LOGGER.info("Waiting for Postgres (attempt %s/%s)", attempt, attempts)
            time.sleep(1)


def geoserver_request(method: str, path: str, **kwargs: Any) -> requests.Response:
    attempts = 3 if method.upper() == "GET" else 1
    for attempt in range(1, attempts + 1):
        try:
            return requests.request(
                method,
                f"{GEOSERVER_REST_URL}/{path.lstrip('/')}",
                auth=GEOSERVER_AUTH,
                timeout=GEOSERVER_REQUEST_TIMEOUT_SECONDS,
                **kwargs,
            )
        except requests.RequestException:
            if attempt == attempts:
                raise
            LOGGER.warning(
                "GeoServer %s %s failed during startup; retrying (%s/%s)",
                method,
                path,
                attempt,
                attempts,
            )
            time.sleep(2 * attempt)
    raise AssertionError("unreachable")


def wait_for_geoserver(attempts: int = 600) -> None:
    for attempt in range(1, attempts + 1):
        try:
            response = geoserver_request("GET", "about/version")
            if response.ok:
                LOGGER.info("GeoServer is ready")
                return
        except requests.RequestException:
            pass

        if attempt == attempts:
            raise RuntimeError("GeoServer did not become ready")
        if attempt == 1 or attempt % 30 == 0:
            LOGGER.info("Waiting for GeoServer (attempt %s/%s)", attempt, attempts)
        time.sleep(1)


def ensure_workspace() -> None:
    response = geoserver_request("GET", f"workspaces/{WORKSPACE}.json")
    if response.status_code == 200:
        return
    if response.status_code != 404:
        response.raise_for_status()

    payload = f"<workspace><name>{escape(WORKSPACE)}</name></workspace>"
    response = geoserver_request(
        "POST",
        "workspaces",
        headers={"Content-Type": "text/xml"},
        data=payload,
    )
    response.raise_for_status()
    LOGGER.info("Created GeoServer workspace %s", WORKSPACE)


def datastore_xml() -> str:
    parameters = {
        "host": DB_CONN["host"],
        "port": str(DB_CONN["port"]),
        "database": DB_CONN["dbname"],
        "user": DB_CONN["user"],
        "passwd": DB_CONN["password"],
        "dbtype": "postgis",
        "Expose primary keys": "true",
        "schema": "public",
        "namespace": f"https://reformers01.ewi.tudelft.nl/id/workspace/{WORKSPACE}",
    }
    entries = "".join(
        f'<entry key="{escape(key)}">{escape(value)}</entry>'
        for key, value in parameters.items()
    )
    return (
        "<dataStore>"
        f"<name>{escape(DATASTORE)}</name>"
        f"<connectionParameters>{entries}</connectionParameters>"
        "</dataStore>"
    )


def ensure_datastore() -> None:
    path = f"workspaces/{WORKSPACE}/datastores/{DATASTORE}"
    existing = geoserver_request("GET", f"{path}.json")
    payload = datastore_xml()
    headers = {"Content-Type": "text/xml"}

    if existing.status_code == 404:
        response = geoserver_request(
            "POST",
            f"workspaces/{WORKSPACE}/datastores",
            headers=headers,
            data=payload,
        )
        response.raise_for_status()
        LOGGER.info("Created GeoServer datastore %s", DATASTORE)
        return
    existing.raise_for_status()

    response = geoserver_request("PUT", path, headers=headers, data=payload)
    response.raise_for_status()
    reset_response = geoserver_request("POST", "reset")
    reset_response.raise_for_status()
    LOGGER.info("Reset GeoServer datastore connections after configuration update")
    LOGGER.info("Refreshed credentials for GeoServer datastore %s", DATASTORE)


def ensure_feature_type(layer_name: str, title: str, srs: str) -> None:
    global_layer = geoserver_request("GET", f"layers/{WORKSPACE}:{layer_name}.json")
    if global_layer.status_code == 200:
        return
    if global_layer.status_code != 404:
        global_layer.raise_for_status()

    feature_type_path = f"workspaces/{WORKSPACE}/datastores/{DATASTORE}/featuretypes"
    payload = (
        "<featureType>"
        f"<name>{escape(layer_name)}</name>"
        f"<nativeName>{escape(layer_name)}</nativeName>"
        f"<title>{escape(title)}</title>"
        f"<srs>{escape(srs)}</srs>"
        "<enabled>true</enabled>"
        "</featureType>"
    )
    response = geoserver_request(
        "POST",
        feature_type_path,
        headers={"Content-Type": "text/xml"},
        data=payload,
    )
    response.raise_for_status()
    LOGGER.info("Published GeoServer layer %s:%s", WORKSPACE, layer_name)


def create_pc6_table(cursor: Any) -> None:
    cursor.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS public.{PC6_TABLE} (
            postcode6 VARCHAR(6) PRIMARY KEY,
            uri TEXT UNIQUE NOT NULL,
            p6_gasm3_2023 DOUBLE PRECISION NOT NULL,
            p6_kwh_2023 DOUBLE PRECISION NOT NULL,
            p6_kwh_productie_2023 DOUBLE PRECISION NOT NULL,
            datacompleetheid SMALLINT NOT NULL
                CHECK (datacompleetheid BETWEEN 0 AND 3),
            datacompleetheid_label TEXT NOT NULL,
            datacompleetheid_method TEXT NOT NULL,
            evidence_summary TEXT NOT NULL,
            source_feature_hash CHAR(64) NOT NULL,
            last_updated TIMESTAMPTZ NOT NULL,
            geom geometry(MultiPolygon, 4326) NOT NULL
        )
        """
    )
    cursor.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{PC6_TABLE}_geom
        ON public.{PC6_TABLE} USING GIST (geom)
        """
    )


def record_values(record: Pc6Record, published_at: datetime) -> tuple[Any, ...]:
    return (
        record.postcode6,
        record.uri,
        record.p6_gasm3_2023,
        record.p6_kwh_2023,
        record.p6_kwh_productie_2023,
        record.datacompleetheid,
        record.datacompleetheid_label,
        record.datacompleetheid_method,
        record.evidence_summary,
        record.source_feature_hash,
        published_at,
        record.geometry_json,
    )


def sync_pc6_records(records: list[Pc6Record]) -> dict[str, int]:
    published_at = datetime.now(timezone.utc)
    with psycopg2.connect(**DB_CONN) as connection:
        with connection.cursor() as cursor:
            create_pc6_table(cursor)
            cursor.execute(
                f"""
                CREATE TEMP TABLE pc6_stage
                (LIKE public.{PC6_TABLE} INCLUDING DEFAULTS)
                ON COMMIT DROP
                """
            )
            execute_values(
                cursor,
                """
                INSERT INTO pc6_stage (
                    postcode6, uri, p6_gasm3_2023, p6_kwh_2023,
                    p6_kwh_productie_2023, datacompleetheid,
                    datacompleetheid_label, datacompleetheid_method,
                    evidence_summary, source_feature_hash, last_updated, geom
                ) VALUES %s
                """,
                [record_values(record, published_at) for record in records],
                template=values_template(11),
                page_size=250,
            )
            cursor.execute(
                f"""
                INSERT INTO public.{PC6_TABLE} AS current (
                    postcode6, uri, p6_gasm3_2023, p6_kwh_2023,
                    p6_kwh_productie_2023, datacompleetheid,
                    datacompleetheid_label, datacompleetheid_method,
                    evidence_summary, source_feature_hash, last_updated, geom
                )
                SELECT
                    postcode6, uri, p6_gasm3_2023, p6_kwh_2023,
                    p6_kwh_productie_2023, datacompleetheid,
                    datacompleetheid_label, datacompleetheid_method,
                    evidence_summary, source_feature_hash, last_updated, geom
                FROM pc6_stage
                WHERE TRUE
                ON CONFLICT (postcode6) DO UPDATE SET
                    uri = EXCLUDED.uri,
                    p6_gasm3_2023 = EXCLUDED.p6_gasm3_2023,
                    p6_kwh_2023 = EXCLUDED.p6_kwh_2023,
                    p6_kwh_productie_2023 = EXCLUDED.p6_kwh_productie_2023,
                    datacompleetheid = EXCLUDED.datacompleetheid,
                    datacompleetheid_label = EXCLUDED.datacompleetheid_label,
                    datacompleetheid_method = EXCLUDED.datacompleetheid_method,
                    evidence_summary = EXCLUDED.evidence_summary,
                    source_feature_hash = EXCLUDED.source_feature_hash,
                    last_updated = EXCLUDED.last_updated,
                    geom = EXCLUDED.geom
                WHERE current.source_feature_hash
                    IS DISTINCT FROM EXCLUDED.source_feature_hash
                """
            )
            changed = cursor.rowcount
            cursor.execute(
                f"""
                DELETE FROM public.{PC6_TABLE} AS current
                WHERE NOT EXISTS (
                    SELECT 1 FROM pc6_stage
                    WHERE pc6_stage.postcode6 = current.postcode6
                )
                """
            )
            deleted = cursor.rowcount
            cursor.execute(
                f"SELECT COUNT(*), COUNT(DISTINCT postcode6) FROM public.{PC6_TABLE}"
            )
            total, unique_ids = cursor.fetchone()

    if total != unique_ids or total != len(records):
        raise RuntimeError(
            f"PC6 publication mismatch: source={len(records)} total={total} "
            f"unique={unique_ids}"
        )
    return {"changed": changed, "deleted": deleted, "total": total}


def publish_pc6() -> None:
    records = load_pc6_records(PC6_SOURCE_PATH, PC6_CONFIG)
    stats = sync_pc6_records(records)
    ensure_feature_type(PC6_LAYER, PC6_CONFIG["title"], PC6_CONFIG["source"]["crs"])
    LOGGER.info(
        "PC6 layer synchronized: total=%s changed=%s deleted=%s",
        stats["total"],
        stats["changed"],
        stats["deleted"],
    )


def create_pv_table(cursor: Any) -> None:
    cursor.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    property_definitions = ",\n            ".join(
        f"{name} {PV_SQL_TYPES[name]}" for name in PV_PROPERTY_FIELDS
    )
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS public.{PV_TABLE} (
            {property_definitions},
            release_commit CHAR(40) NOT NULL,
            container_image TEXT NOT NULL,
            output_id TEXT NOT NULL,
            source_feature_hash CHAR(64) NOT NULL,
            published_at TIMESTAMPTZ NOT NULL,
            geom geometry(MultiPolygon, 4326) NOT NULL
        )
        """
    )
    cursor.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{PV_TABLE}_geom
        ON public.{PV_TABLE} USING GIST (geom)
        """
    )


def pv_record_values(
    record: PvCapacityRecord,
    artifact: PvArtifact,
    published_at: datetime,
) -> tuple[Any, ...]:
    return (
        *(record.properties[field] for field in PV_PROPERTY_FIELDS),
        artifact.release_commit,
        artifact.container_image,
        artifact.output_id,
        record.source_feature_hash,
        published_at,
        record.geometry_json,
    )


def sync_pv_records(artifact: PvArtifact) -> dict[str, int]:
    published_at = datetime.now(timezone.utc)
    columns = (
        *PV_PROPERTY_FIELDS,
        "release_commit",
        "container_image",
        "output_id",
        "source_feature_hash",
        "published_at",
        "geom",
    )
    column_list = ", ".join(columns)
    update_columns = [name for name in columns if name not in {"feature_id", "geom"}]
    update_clause = ",\n                    ".join(
        f"{name} = EXCLUDED.{name}" for name in update_columns
    )
    template = values_template(len(columns) - 1)

    with psycopg2.connect(**DB_CONN) as connection:
        with connection.cursor() as cursor:
            create_pv_table(cursor)
            cursor.execute(
                f"""
                CREATE TEMP TABLE pv_stage
                (LIKE public.{PV_TABLE} INCLUDING DEFAULTS)
                ON COMMIT DROP
                """
            )
            execute_values(
                cursor,
                f"INSERT INTO pv_stage ({column_list}) VALUES %s",
                [pv_record_values(record, artifact, published_at) for record in artifact.records],
                template=template,
                page_size=250,
            )
            cursor.execute(
                f"""
                INSERT INTO public.{PV_TABLE} AS current ({column_list})
                SELECT {column_list}
                FROM pv_stage
                WHERE TRUE
                ON CONFLICT (feature_id) DO UPDATE SET
                    {update_clause},
                    geom = EXCLUDED.geom
                WHERE current.source_feature_hash
                    IS DISTINCT FROM EXCLUDED.source_feature_hash
                   OR current.release_commit
                    IS DISTINCT FROM EXCLUDED.release_commit
                   OR current.container_image
                    IS DISTINCT FROM EXCLUDED.container_image
                """
            )
            changed = cursor.rowcount
            cursor.execute(
                f"""
                DELETE FROM public.{PV_TABLE} AS current
                WHERE NOT EXISTS (
                    SELECT 1 FROM pv_stage
                    WHERE pv_stage.feature_id = current.feature_id
                )
                """
            )
            deleted = cursor.rowcount
            cursor.execute(
                f"SELECT COUNT(*), COUNT(DISTINCT feature_id) FROM public.{PV_TABLE}"
            )
            total, unique_ids = cursor.fetchone()

    if total != unique_ids or total != len(artifact.records):
        raise RuntimeError(
            f"PV publication mismatch: source={len(artifact.records)} "
            f"total={total} unique={unique_ids}"
        )
    return {"changed": changed, "deleted": deleted, "total": total}


def publish_pv() -> PvArtifact:
    artifact = fetch_pv_artifact(
        PV_API_URL,
        expected_release_commit=PV_EXPECTED_RELEASE_COMMIT,
        expected_container_image=PV_EXPECTED_CONTAINER_IMAGE,
        expected_model_version=PV_CONFIG["model_version"],
        expected_metadata_contract_version=PV_CONFIG["metadata_contract_version"],
    )
    stats = sync_pv_records(artifact)
    ensure_feature_type(PV_LAYER, PV_CONFIG["title"], PV_CONFIG["source"]["crs"])
    LOGGER.info(
        "PV layer synchronized: total=%s changed=%s deleted=%s output=%s",
        stats["total"],
        stats["changed"],
        stats["deleted"],
        artifact.output_id,
    )
    return artifact


def publish_grid() -> GridArtifact:
    artifact = fetch_grid_artifact(
        GRID_API_URL,
        bbox=GRID_EXPORT_BBOX,
        expected_release_commit=GRID_EXPECTED_RELEASE_COMMIT,
        expected_container_digest=GRID_EXPECTED_CONTAINER_DIGEST,
        expected_model_version=GRID_LINES_CONFIG["model_version"],
        expected_contract_version=GRID_LINES_CONFIG["metadata_contract_version"],
        expected_data_mode=GRID_EXPECTED_DATA_MODE,
    )
    for layer_id, config in GRID_CONFIGS.items():
        stats = sync_grid_layer(
            DB_CONN,
            table=GRID_TABLES[layer_id],
            layer_id=layer_id,
            artifact=artifact,
        )
        ensure_feature_type(
            config["geoserver_layer"], config["title"], config["source"]["crs"]
        )
        LOGGER.info(
            "%s synchronized: total=%s changed=%s deleted=%s output=%s",
            layer_id,
            stats["total"],
            stats["changed"],
            stats["deleted"],
            artifact.output_ids[layer_id],
        )
    reset_response = geoserver_request("POST", "reset")
    reset_response.raise_for_status()
    LOGGER.info("Reset GeoServer datastore connections after Grid publication")
    return artifact


def publish_wind() -> WindArtifact:
    artifact = fetch_wind_artifact(
        WIND_API_URL,
        expected_release_commit=WIND_EXPECTED_RELEASE_COMMIT,
        expected_container_image=WIND_EXPECTED_CONTAINER_IMAGE,
        expected_container_digest=WIND_EXPECTED_CONTAINER_DIGEST,
        expected_model_version=WIND_CONFIG["model_version"],
        expected_contract_version=WIND_CONFIG["metadata_contract_version"],
        expected_schema_contract_version=WIND_CONFIG["schema_contract_version"],
        expected_data_mode=WIND_EXPECTED_DATA_MODE,
    )
    stats = sync_wind_layer(DB_CONN, table=WIND_TABLE, artifact=artifact)
    ensure_feature_type(
        WIND_LAYER, WIND_CONFIG["title"], WIND_CONFIG["source"]["crs"]
    )
    LOGGER.info(
        "Wind layer synchronized: total=%s changed=%s deleted=%s output=%s",
        stats["total"],
        stats["changed"],
        stats["deleted"],
        artifact.output_id,
    )
    return artifact


def publish_heat() -> HeatArtifact:
    first_config = next(iter(HEAT_CONFIGS.values()))
    artifact = fetch_heat_artifact(
        HEAT_API_URL,
        expected_release_commit=HEAT_EXPECTED_RELEASE_COMMIT,
        expected_container_digest=HEAT_EXPECTED_CONTAINER_DIGEST,
        expected_model_version=first_config["model_version"],
        expected_contract_version=first_config["metadata_contract_version"],
        expected_schema_contract_version=first_config["schema_contract_version"],
        expected_data_mode=HEAT_EXPECTED_DATA_MODE,
    )
    stats = sync_heat_layers(DB_CONN, tables=HEAT_TABLES, artifact=artifact)
    for layer_id, config in HEAT_CONFIGS.items():
        ensure_feature_type(
            config["geoserver_layer"], config["title"], config["source"]["crs"]
        )
        layer_stats = stats[layer_id]
        LOGGER.info(
            "Heat %s synchronized: total=%s changed=%s deleted=%s output=%s",
            layer_id,
            layer_stats["total"],
            layer_stats["changed"],
            layer_stats["deleted"],
            artifact.layers[layer_id].output_id,
        )
    return artifact


def publish_ev() -> EvArtifact:
    artifact = fetch_ev_artifact(
        EV_API_URL,
        expected_release_commit=EV_EXPECTED_RELEASE_COMMIT,
        expected_container_image=EV_EXPECTED_CONTAINER_IMAGE,
        expected_model_version=EV_CONFIG["model_version"],
        expected_metadata_contract_version=EV_CONFIG["metadata_contract_version"],
        expected_quality_method_version=EV_CONFIG["data_quality"]["method_version"],
    )
    stats = sync_ev_layer(DB_CONN, table=EV_TABLE, records=artifact.records)
    ensure_feature_type(
        EV_LAYER, EV_CONFIG["title"], EV_CONFIG["source"]["crs"]
    )
    LOGGER.info(
        "EV charger layer synchronized: total=%s changed=%s deleted=%s output=%s",
        stats["total"],
        stats["changed"],
        stats["deleted"],
        artifact.output_id,
    )
    return artifact


def publish_ev() -> EvArtifact:
    artifact = fetch_ev_artifact(
        EV_API_URL,
        expected_release_commit=EV_EXPECTED_RELEASE_COMMIT,
        expected_container_image=EV_EXPECTED_CONTAINER_IMAGE,
        expected_model_version=EV_CONFIG["model_version"],
        expected_metadata_contract_version=EV_CONFIG["metadata_contract_version"],
        expected_quality_method_version=EV_CONFIG["data_quality"]["method_version"],
    )
    stats = sync_model_layer(
        DB_CONN,
        table=EV_TABLE,
        layer_id="public_ev_chargers",
        records=artifact.records,
    )
    ensure_feature_type(EV_LAYER, EV_CONFIG["title"], EV_CONFIG["source"]["crs"])
    LOGGER.info(
        "EV charger layer synchronized: total=%s changed=%s deleted=%s output=%s",
        stats["total"],
        stats["changed"],
        stats["deleted"],
        artifact.output_id,
    )
    return artifact


def publish_consumption() -> ConsumptionArtifact:
    artifact = fetch_consumption_artifact(
        CONSUMPTION_API_URL,
        expected_release_commit=CONSUMPTION_EXPECTED_RELEASE_COMMIT,
        expected_container_image=CONSUMPTION_EXPECTED_CONTAINER_IMAGE,
        expected_model_version=CONSUMPTION_CONFIG["model_version"],
        expected_metadata_contract_version=CONSUMPTION_CONFIG[
            "metadata_contract_version"
        ],
        expected_quality_rule_version=CONSUMPTION_CONFIG["data_quality"][
            "method_version"
        ],
    )
    stats = sync_model_layer(
        DB_CONN,
        table=CONSUMPTION_TABLE,
        layer_id="electricity_consumption_areas",
        records=artifact.records,
    )
    ensure_feature_type(
        CONSUMPTION_LAYER,
        CONSUMPTION_CONFIG["title"],
        CONSUMPTION_CONFIG["source"]["crs"],
    )
    LOGGER.info(
        "Consumption area layer synchronized: total=%s changed=%s deleted=%s output=%s",
        stats["total"],
        stats["changed"],
        stats["deleted"],
        artifact.output_id,
    )
    return artifact


def create_solar_table() -> None:
    with psycopg2.connect(**DB_CONN) as connection:
        with connection.cursor() as cursor:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS postgis")
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS public.{SOLAR_TABLE} (
                    id INTEGER PRIMARY KEY,
                    value DOUBLE PRECISION,
                    geom geometry(Point, 4326) NOT NULL
                )
                """
            )


def latest_solar_forecast() -> float | None:
    with psycopg2.connect(**DB_CONN) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT value
                FROM public.forecasts
                WHERE dp_id = (
                    SELECT id
                    FROM public.data_points
                    WHERE name = 'p_forecast'
                      AND data_provider = 'Illuminator'
                    LIMIT 1
                )
                ORDER BY fc_time DESC
                LIMIT 1
                """
            )
            row = cursor.fetchone()
    return float(row[0]) if row else None


def update_solar_layer() -> None:
    value = latest_solar_forecast()
    if value is None:
        LOGGER.info("No Illuminator p_forecast is available yet")
        return

    with psycopg2.connect(**DB_CONN) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                INSERT INTO public.{SOLAR_TABLE} (id, value, geom)
                VALUES (1, %s, ST_SetSRID(ST_MakePoint(4.3735, 52.0022), 4326))
                ON CONFLICT (id) DO UPDATE SET value = EXCLUDED.value
                """,
                (value,),
            )
    LOGGER.info("Tutorial solar point updated: value=%s", value)


def source_signature(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size


def run() -> None:
    publish_models = parse_publish_models(os.getenv("PUBLISH_MODELS"))
    LOGGER.info("Startup publication scope: %s", ",".join(publish_models))

    wait_for_postgres()
    wait_for_geoserver()
    ensure_workspace()
    ensure_datastore()

    if "pc6" in publish_models:
        publish_pc6()
    if "pv" in publish_models:
        publish_pv()
    if "grid" in publish_models:
        publish_grid()
    if "wind" in publish_models:
        publish_wind()
    if "heat" in publish_models:
        publish_heat()
    if "ev" in publish_models:
        publish_ev()
    if "consumption" in publish_models:
        publish_consumption()

    # This tutorial layer is internal platform state, not an independent model.
    create_solar_table()
    ensure_feature_type(SOLAR_LAYER, "Tutorial Solar Panel", "EPSG:4326")
    try:
        update_solar_layer()
    except psycopg2.Error:
        LOGGER.warning("Tutorial solar point is waiting for RDP forecast tables", exc_info=True)

    if PUBLISH_ONCE:
        return

    if os.getenv("PUBLISH_MODELS"):
        LOGGER.info("Startup publication complete; monitoring all models for changes")

    last_pc6_signature = source_signature(PC6_SOURCE_PATH)
    last_pv_signature = get_pv_readiness_signature(PV_API_URL)
    last_grid_signature = get_grid_readiness_signature(GRID_API_URL)
    last_wind_signature = get_wind_readiness_signature(
        WIND_API_URL, expected_data_mode=WIND_EXPECTED_DATA_MODE
    )
    last_heat_signature = get_heat_readiness_signature(
        HEAT_API_URL, expected_data_mode=HEAT_EXPECTED_DATA_MODE
    )
    last_ev_signature = get_ev_readiness_signature(EV_API_URL)
    last_consumption_signature = get_consumption_readiness_signature(
        CONSUMPTION_API_URL
    )
    while True:
        time.sleep(PUBLISH_INTERVAL_SECONDS)
        current_signature = source_signature(PC6_SOURCE_PATH)
        if current_signature != last_pc6_signature:
            publish_pc6()
            last_pc6_signature = current_signature
        try:
            current_pv_signature = get_pv_readiness_signature(PV_API_URL)
            if current_pv_signature != last_pv_signature:
                publish_pv()
                last_pv_signature = current_pv_signature
        except (RuntimeError, ValueError):
            LOGGER.warning(
                "Could not check or refresh the PV capacity layer",
                exc_info=True,
            )
        try:
            current_consumption_signature = get_consumption_readiness_signature(
                CONSUMPTION_API_URL
            )
            if current_consumption_signature != last_consumption_signature:
                publish_consumption()
                last_consumption_signature = current_consumption_signature
        except (requests.RequestException, RuntimeError, TypeError, ValueError):
            LOGGER.warning(
                "Could not check or refresh the Consumption area layer",
                exc_info=True,
            )
        try:
            current_grid_signature = get_grid_readiness_signature(GRID_API_URL)
            if current_grid_signature != last_grid_signature:
                publish_grid()
                last_grid_signature = current_grid_signature
        except (RuntimeError, ValueError):
            LOGGER.warning(
                "Could not check or refresh the grid layers",
                exc_info=True,
            )
        try:
            current_wind_signature = get_wind_readiness_signature(
                WIND_API_URL, expected_data_mode=WIND_EXPECTED_DATA_MODE
            )
            if current_wind_signature != last_wind_signature:
                publish_wind()
                last_wind_signature = current_wind_signature
        except (RuntimeError, ValueError):
            LOGGER.warning(
                "Could not check or refresh the Wind turbine layer",
                exc_info=True,
            )
        try:
            current_heat_signature = get_heat_readiness_signature(
                HEAT_API_URL, expected_data_mode=HEAT_EXPECTED_DATA_MODE
            )
            if current_heat_signature != last_heat_signature:
                publish_heat()
                last_heat_signature = current_heat_signature
        except (RuntimeError, ValueError):
            LOGGER.warning(
                "Could not check or refresh the Heat layers",
                exc_info=True,
            )
        try:
            current_ev_signature = get_ev_readiness_signature(EV_API_URL)
            if current_ev_signature != last_ev_signature:
                publish_ev()
                last_ev_signature = current_ev_signature
        except (requests.RequestException, RuntimeError, TypeError, ValueError):
            LOGGER.warning(
                "Could not check or refresh the EV charger layer",
                exc_info=True,
            )
        try:
            update_solar_layer()
        except psycopg2.Error:
            LOGGER.warning("Could not refresh tutorial solar point", exc_info=True)


if __name__ == "__main__":
    run()
