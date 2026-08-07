import json
from datetime import datetime, timezone
from typing import Any

import psycopg2
from grid import (
    GRID_LAYER_FIELDS,
    GRID_LINE_FIELDS,
    GRID_TRANSFORMER_FIELDS,
    GridArtifact,
    GridRecord,
)
from postgis_sql import multiline_values_template, point_values_template
from psycopg2.extras import Json, execute_values


GRID_COMMON_SQL_TYPES = {
    "feature_id": "TEXT UNIQUE NOT NULL",
    "component_id": "TEXT PRIMARY KEY",
    "persistent_uri": "TEXT UNIQUE NOT NULL",
    "component_type": "TEXT NOT NULL",
    "voltage_level": "TEXT NOT NULL",
    "nominal_voltage": "DOUBLE PRECISION CHECK (nominal_voltage >= 0)",
    "nominal_voltage_unit": "TEXT NOT NULL",
    "model_id": "TEXT NOT NULL",
    "model_version": "TEXT NOT NULL",
    "method_version": "TEXT NOT NULL",
    "grid_data_version": "TEXT NOT NULL",
    "source_reference_period": "TEXT",
    "source_modified_at": "TIMESTAMPTZ",
    "source_retrieved_at": "TIMESTAMPTZ NOT NULL",
    "source_last_updated": "TIMESTAMPTZ",
    "cache_generated_at": "TIMESTAMPTZ NOT NULL",
    "datacompleetheid": "SMALLINT NOT NULL CHECK (datacompleetheid BETWEEN 0 AND 3)",
    "datacompleetheid_label": "TEXT NOT NULL",
    "datacompleetheid_rule_version": "TEXT NOT NULL",
    "datacompleetheid_assessed_at": "TIMESTAMPTZ NOT NULL",
    "datacompleetheid_reason_codes": "JSONB NOT NULL",
    "datacompleetheid_summary": "TEXT NOT NULL",
    "run_id": "UUID NOT NULL",
    "output_id": "UUID NOT NULL",
    "model_run_at": "TIMESTAMPTZ NOT NULL",
    "output_generated_at": "TIMESTAMPTZ NOT NULL",
}

GRID_LINE_SQL_TYPES = {
    **GRID_COMMON_SQL_TYPES,
    "model_component_name": "TEXT",
    "length_km": "DOUBLE PRECISION CHECK (length_km >= 0)",
    "in_service": "BOOLEAN",
    "evidence_status": "TEXT NOT NULL",
    "connected_transformer_ids": "JSONB NOT NULL",
    "serving_transformer_id": "TEXT",
}

GRID_TRANSFORMER_SQL_TYPES = {
    **GRID_COMMON_SQL_TYPES,
    "model_component_name": "TEXT",
    "transformer_type": "TEXT NOT NULL",
    "primary_nominal_voltage_kv": "DOUBLE PRECISION CHECK (primary_nominal_voltage_kv >= 0)",
    "secondary_nominal_voltage_kv": "DOUBLE PRECISION CHECK (secondary_nominal_voltage_kv >= 0)",
    "rated_power_kva": "DOUBLE PRECISION CHECK (rated_power_kva >= 0)",
    "in_service": "BOOLEAN",
    "source_station_objectid": "TEXT",
    "source_station_name": "TEXT",
}

GRID_LAYER_SQL = {
    "grid_lines": {
        "fields": GRID_LINE_FIELDS,
        "types": GRID_LINE_SQL_TYPES,
        "geometry_type": "MultiLineString",
        "template": multiline_values_template,
    },
    "grid_transformers": {
        "fields": GRID_TRANSFORMER_FIELDS,
        "types": GRID_TRANSFORMER_SQL_TYPES,
        "geometry_type": "Point",
        "template": point_values_template,
    },
}


def create_grid_table(cursor: Any, table: str, layer_id: str) -> None:
    config = GRID_LAYER_SQL[layer_id]
    property_definitions = ",\n            ".join(
        f"{name} {config['types'][name]}" for name in config["fields"]
    )
    cursor.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS public.{table} (
            {property_definitions},
            release_commit CHAR(40) NOT NULL,
            container_digest TEXT NOT NULL,
            source_feature_hash CHAR(64) NOT NULL,
            published_at TIMESTAMPTZ NOT NULL,
            geom geometry({config['geometry_type']}, 4326) NOT NULL
        )
        """
    )
    cursor.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{table}_geom
        ON public.{table} USING GIST (geom)
        """
    )


def grid_record_values(
    record: GridRecord,
    artifact: GridArtifact,
    published_at: datetime,
) -> tuple[Any, ...]:
    values = []
    for field in GRID_LAYER_FIELDS[record.layer_id]:
        value = record.properties[field]
        if field in {"connected_transformer_ids", "datacompleetheid_reason_codes"}:
            value = Json(
                value,
                dumps=lambda item: json.dumps(item, separators=(",", ":")),
            )
        values.append(value)
    return (
        *values,
        artifact.release_commit,
        artifact.container_digest,
        record.source_feature_hash,
        published_at,
        record.geometry_json,
    )


def sync_grid_layer(
    db_conn: dict[str, Any],
    *,
    table: str,
    layer_id: str,
    artifact: GridArtifact,
) -> dict[str, int]:
    records = artifact.records_by_layer[layer_id]
    config = GRID_LAYER_SQL[layer_id]
    published_at = datetime.now(timezone.utc)
    columns = (
        *config["fields"],
        "release_commit",
        "container_digest",
        "source_feature_hash",
        "published_at",
        "geom",
    )
    column_list = ", ".join(columns)
    update_columns = [
        name for name in columns if name not in {"component_id", "geom"}
    ]
    update_clause = ",\n                    ".join(
        f"{name} = EXCLUDED.{name}" for name in update_columns
    )

    with psycopg2.connect(**db_conn) as connection:
        with connection.cursor() as cursor:
            create_grid_table(cursor, table, layer_id)
            stage_table = f"{table}_stage"
            cursor.execute(
                f"""
                CREATE TEMP TABLE {stage_table}
                (LIKE public.{table} INCLUDING DEFAULTS)
                ON COMMIT DROP
                """
            )
            execute_values(
                cursor,
                f"INSERT INTO {stage_table} ({column_list}) VALUES %s",
                [
                    grid_record_values(record, artifact, published_at)
                    for record in records
                ],
                template=config["template"](len(columns) - 1),
                page_size=500,
            )
            cursor.execute(
                f"""
                INSERT INTO public.{table} AS current ({column_list})
                SELECT {column_list}
                FROM {stage_table}
                WHERE TRUE
                ON CONFLICT (component_id) DO UPDATE SET
                    {update_clause},
                    geom = EXCLUDED.geom
                WHERE current.source_feature_hash
                    IS DISTINCT FROM EXCLUDED.source_feature_hash
                   OR current.release_commit
                    IS DISTINCT FROM EXCLUDED.release_commit
                   OR current.container_digest
                    IS DISTINCT FROM EXCLUDED.container_digest
                """
            )
            changed = cursor.rowcount
            cursor.execute(
                f"""
                DELETE FROM public.{table} AS current
                WHERE NOT EXISTS (
                    SELECT 1 FROM {stage_table}
                    WHERE {stage_table}.component_id = current.component_id
                )
                """
            )
            deleted = cursor.rowcount
            cursor.execute(
                f"SELECT COUNT(*), COUNT(DISTINCT component_id) FROM public.{table}"
            )
            total, unique_ids = cursor.fetchone()

    if total != unique_ids or total != len(records):
        raise RuntimeError(
            f"{layer_id} publication mismatch: source={len(records)} "
            f"total={total} unique={unique_ids}"
        )
    return {"changed": changed, "deleted": deleted, "total": total}
