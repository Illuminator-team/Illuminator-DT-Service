import json
from datetime import datetime, timezone
from typing import Any

import psycopg2
from postgis_sql import point_values_template
from psycopg2.extras import Json, execute_values
from wind import WIND_JSON_FIELDS, WIND_PROPERTY_FIELDS, WindArtifact, WindRecord

WIND_SQL_TYPES = {
    "feature_id": "TEXT PRIMARY KEY",
    "persistent_uri": "TEXT UNIQUE NOT NULL",
    "source_feature_id": "TEXT UNIQUE NOT NULL",
    "capacity_kw": "DOUBLE PRECISION CHECK (capacity_kw >= 0)",
    "capacity_unit": "TEXT NOT NULL",
    "capacity_mw": "DOUBLE PRECISION CHECK (capacity_mw >= 0)",
    "capacity_mw_unit": "TEXT NOT NULL",
    "hub_height_m": "DOUBLE PRECISION CHECK (hub_height_m >= 0)",
    "hub_height_unit": "TEXT NOT NULL",
    "rotor_diameter_m": "DOUBLE PRECISION CHECK (rotor_diameter_m >= 0)",
    "rotor_diameter_unit": "TEXT NOT NULL",
    "tip_height_m": "DOUBLE PRECISION CHECK (tip_height_m >= 0)",
    "tip_height_unit": "TEXT NOT NULL",
    "rotor_swept_area_m2": "DOUBLE PRECISION CHECK (rotor_swept_area_m2 >= 0)",
    "rotor_swept_area_unit": "TEXT NOT NULL",
    "name": "TEXT",
    "turbine_type": "TEXT",
    "municipality": "TEXT NOT NULL",
    "province": "TEXT NOT NULL",
    "country": "TEXT NOT NULL",
    "surface": "TEXT NOT NULL",
    "source_reference_date": "TEXT NOT NULL",
    "modeled_annual_energy_kwh": "DOUBLE PRECISION CHECK (modeled_annual_energy_kwh >= 0)",
    "modeled_annual_energy_unit": "TEXT NOT NULL",
    "modeled_capacity_factor": "DOUBLE PRECISION CHECK (modeled_capacity_factor BETWEEN 0 AND 1)",
    "modeled_peak_power_kw": "DOUBLE PRECISION CHECK (modeled_peak_power_kw >= 0)",
    "modeled_peak_power_unit": "TEXT NOT NULL",
    "modeled_profile_year": "INTEGER",
    "modeled_profile_interval": "TEXT",
    "profile_id": "TEXT",
    "profile_transport_available": "BOOLEAN NOT NULL",
    "inventory_evidence_status": "TEXT NOT NULL",
    "geometry_evidence_status": "TEXT NOT NULL",
    "capacity_evidence_status": "TEXT NOT NULL",
    "derived_geometry_status": "TEXT NOT NULL",
    "generation_evidence_status": "TEXT NOT NULL",
    "quality_flags": "JSONB NOT NULL",
    "datacompleetheid": "SMALLINT NOT NULL CHECK (datacompleetheid BETWEEN 0 AND 3)",
    "datacompleetheid_label": "TEXT NOT NULL",
    "datacompleetheid_rule_version": "TEXT NOT NULL",
    "datacompleetheid_assessed_at": "TIMESTAMPTZ NOT NULL",
    "datacompleetheid_reason_codes": "JSONB NOT NULL",
    "datacompleetheid_evidence": "JSONB NOT NULL",
    "completeness_reason": "TEXT NOT NULL",
    "source_reference_period": "TEXT",
    "source_modified_at": "TIMESTAMPTZ",
    "source_last_updated": "TIMESTAMPTZ",
    "source_retrieved_at": "TIMESTAMPTZ",
    "source_evidence": "JSONB NOT NULL",
    "limitations": "JSONB NOT NULL",
    "data_mode": "TEXT NOT NULL",
    "model_id": "TEXT NOT NULL",
    "model_version": "TEXT NOT NULL",
    "contract_version": "TEXT NOT NULL",
    "schema_contract_version": "TEXT NOT NULL",
    "git_commit": "CHAR(40) NOT NULL",
    "container_image": "TEXT NOT NULL",
    "model_run_at": "TIMESTAMPTZ NOT NULL",
    "output_generated_at": "TIMESTAMPTZ NOT NULL",
    "run_id": "UUID NOT NULL",
    "output_id": "UUID NOT NULL",
}


def create_wind_table(cursor: Any, table: str) -> None:
    definitions = ",\n            ".join(
        f"{name} {WIND_SQL_TYPES[name]}" for name in WIND_PROPERTY_FIELDS
    )
    cursor.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS public.{table} (
            {definitions},
            deployment_container_digest TEXT NOT NULL,
            source_feature_hash CHAR(64) NOT NULL,
            published_at TIMESTAMPTZ NOT NULL,
            geom geometry(Point, 4326) NOT NULL
        )
        """
    )
    cursor.execute(
        f"CREATE INDEX IF NOT EXISTS idx_{table}_geom ON public.{table} USING GIST (geom)"
    )


def wind_record_values(
    record: WindRecord,
    artifact: WindArtifact,
    published_at: datetime,
) -> tuple[Any, ...]:
    values = []
    for field in WIND_PROPERTY_FIELDS:
        value = record.properties[field]
        if field in WIND_JSON_FIELDS:
            value = Json(value, dumps=lambda item: json.dumps(item, separators=(",", ":")))
        values.append(value)
    return (
        *values,
        artifact.container_digest,
        record.source_feature_hash,
        published_at,
        record.geometry_json,
    )


def sync_wind_layer(
    db_conn: dict[str, Any],
    *,
    table: str,
    artifact: WindArtifact,
) -> dict[str, int]:
    published_at = datetime.now(timezone.utc)
    columns = (
        *WIND_PROPERTY_FIELDS,
        "deployment_container_digest",
        "source_feature_hash",
        "published_at",
        "geom",
    )
    column_list = ", ".join(columns)
    update_columns = [name for name in columns if name not in {"feature_id", "geom"}]
    update_clause = ",\n                    ".join(
        f"{name} = EXCLUDED.{name}" for name in update_columns
    )

    with psycopg2.connect(**db_conn) as connection:
        with connection.cursor() as cursor:
            create_wind_table(cursor, table)
            cursor.execute(
                f"""
                CREATE TEMP TABLE wind_stage
                (LIKE public.{table} INCLUDING DEFAULTS)
                ON COMMIT DROP
                """
            )
            execute_values(
                cursor,
                f"INSERT INTO wind_stage ({column_list}) VALUES %s",
                [wind_record_values(record, artifact, published_at) for record in artifact.records],
                template=point_values_template(len(columns) - 1),
                page_size=100,
            )
            cursor.execute(
                f"""
                INSERT INTO public.{table} AS current ({column_list})
                SELECT {column_list}
                FROM wind_stage
                WHERE TRUE
                ON CONFLICT (feature_id) DO UPDATE SET
                    {update_clause},
                    geom = EXCLUDED.geom
                WHERE current.source_feature_hash
                    IS DISTINCT FROM EXCLUDED.source_feature_hash
                   OR current.git_commit
                    IS DISTINCT FROM EXCLUDED.git_commit
                   OR current.deployment_container_digest
                    IS DISTINCT FROM EXCLUDED.deployment_container_digest
                """
            )
            changed = cursor.rowcount
            cursor.execute(
                f"""
                DELETE FROM public.{table} AS current
                WHERE NOT EXISTS (
                    SELECT 1 FROM wind_stage
                    WHERE wind_stage.feature_id = current.feature_id
                )
                """
            )
            deleted = cursor.rowcount
            cursor.execute(
                f"SELECT COUNT(*), COUNT(DISTINCT feature_id) FROM public.{table}"
            )
            total, unique_ids = cursor.fetchone()

    if total != unique_ids or total != len(artifact.records):
        raise RuntimeError(
            f"Wind publication mismatch: source={len(artifact.records)} "
            f"total={total} unique={unique_ids}"
        )
    return {"changed": changed, "deleted": deleted, "total": total}
