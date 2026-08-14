import json
import re
from datetime import datetime, timezone
from typing import Any

import psycopg2
from heat import (
    HEAT_COMMON_FIELDS,
    HEAT_LAYER_DEFINITIONS,
    HeatArtifact,
    HeatLayerArtifact,
    HeatRecord,
)
from postgis_sql import point_values_template, values_template
from psycopg2.extras import Json, execute_values

IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,62}$")

COMMON_SQL_TYPES = {
    "feature_id": "TEXT PRIMARY KEY",
    "persistent_uri": "TEXT UNIQUE NOT NULL",
    "layer_id": "TEXT NOT NULL",
    "evidence_status": "TEXT NOT NULL",
    "datacompleetheid": "SMALLINT NOT NULL CHECK (datacompleetheid BETWEEN 0 AND 3)",
    "datacompleetheid_label": "TEXT NOT NULL",
    "datacompleetheid_rule_version": "TEXT NOT NULL",
    "fixture_only": "BOOLEAN NOT NULL",
    "quality_evidence": "JSONB NOT NULL",
    "provenance": "JSONB NOT NULL",
    "all_properties": "JSONB NOT NULL",
}

CANONICAL_SQL_TYPES = {
    "consumer_area_id": "TEXT NOT NULL",
    "area_name": "TEXT NOT NULL",
    "reference_year": "INTEGER NOT NULL",
    "reported_connected_share_pct": "DOUBLE PRECISION NOT NULL CHECK (reported_connected_share_pct BETWEEN 0 AND 100)",
    "connected_dwellings_estimate": "INTEGER NOT NULL CHECK (connected_dwellings_estimate >= 0)",
    "heat_demand_estimate_gj_per_year": "DOUBLE PRECISION NOT NULL CHECK (heat_demand_estimate_gj_per_year >= 0)",
    "heat_demand_low_gj_per_year": "DOUBLE PRECISION NOT NULL CHECK (heat_demand_low_gj_per_year >= 0)",
    "heat_demand_high_gj_per_year": "DOUBLE PRECISION NOT NULL CHECK (heat_demand_high_gj_per_year >= 0)",
    "postcode6": "TEXT NOT NULL",
    "allocated_connected_dwellings_est": "INTEGER NOT NULL CHECK (allocated_connected_dwellings_est >= 0)",
    "heat_demand_gj_year_est": "DOUBLE PRECISION NOT NULL CHECK (heat_demand_gj_year_est >= 0)",
    "gas_avg_m3": "DOUBLE PRECISION CHECK (gas_avg_m3 >= 0)",
    "electricity_avg_kwh": "DOUBLE PRECISION CHECK (electricity_avg_kwh >= 0)",
    "inference_class": "TEXT NOT NULL",
    "corroboration": "TEXT NOT NULL",
    "liander_crosscheck_status": "TEXT NOT NULL",
    "development_area_id": "TEXT NOT NULL",
    "development_name": "TEXT NOT NULL",
    "development_phase": "TEXT NOT NULL",
    "status_date": "TIMESTAMPTZ",
    "planned_consumer_scale": "TEXT NOT NULL",
    "planned_heat_source_description": "TEXT NOT NULL",
    "source_name": "TEXT NOT NULL",
    "source_status": "TEXT NOT NULL",
    "technology": "TEXT NOT NULL",
    "consumer_name": "TEXT NOT NULL",
    "connection_evidence": "TEXT NOT NULL",
    "annual_heat_consumption": "DOUBLE PRECISION CHECK (annual_heat_consumption >= 0)",
    "source_type": "TEXT NOT NULL",
    "potential_thermal_capacity_mw": "DOUBLE PRECISION CHECK (potential_thermal_capacity_mw >= 0)",
    "temperature_c": "DOUBLE PRECISION",
    "candidate_status": "TEXT",
}

PUBLICATION_COLUMNS = (
    "api_run_id",
    "api_output_id",
    "output_generated_at",
    "model_snapshot_id",
    "release_commit",
    "deployment_container_digest",
    "source_feature_hash",
    "published_at",
    "geom",
)


def _identifier(value: str) -> str:
    if not IDENTIFIER_PATTERN.fullmatch(value):
        raise ValueError(f"Unsafe PostGIS identifier: {value}")
    return value


def create_heat_table(cursor: Any, *, table: str, layer_id: str) -> None:
    table = _identifier(table)
    definition = HEAT_LAYER_DEFINITIONS[layer_id]
    common = ",\n            ".join(
        f"{field} {COMMON_SQL_TYPES[field]}" for field in HEAT_COMMON_FIELDS
    )
    canonical = ",\n            ".join(
        f"{field} {CANONICAL_SQL_TYPES[field]}"
        for field in definition["canonical_fields"]
    )
    geometry_type = "MultiPolygon" if definition["geometry"] == "multipolygon" else "Point"
    cursor.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS public.{table} (
            {common},
            {canonical},
            api_run_id UUID NOT NULL,
            api_output_id UUID NOT NULL,
            output_generated_at TIMESTAMPTZ NOT NULL,
            model_snapshot_id UUID NOT NULL,
            release_commit CHAR(40) NOT NULL,
            deployment_container_digest TEXT NOT NULL,
            source_feature_hash CHAR(64) NOT NULL,
            published_at TIMESTAMPTZ NOT NULL,
            geom geometry({geometry_type}, 4326) NOT NULL
        )
        """
    )
    cursor.execute(
        f"CREATE INDEX IF NOT EXISTS idx_{table}_geom ON public.{table} USING GIST (geom)"
    )


def heat_record_values(
    record: HeatRecord,
    layer_artifact: HeatLayerArtifact,
    artifact: HeatArtifact,
    published_at: datetime,
) -> tuple[Any, ...]:
    common_values = []
    for field in HEAT_COMMON_FIELDS:
        if field == "all_properties":
            value = Json(
                record.properties,
                dumps=lambda item: json.dumps(item, ensure_ascii=True, separators=(",", ":")),
            )
        elif field in {"quality_evidence", "provenance"}:
            value = Json(
                record.properties[field],
                dumps=lambda item: json.dumps(item, ensure_ascii=True, separators=(",", ":")),
            )
        else:
            value = record.properties[field]
        common_values.append(value)
    canonical_values = [
        record.canonical[field]
        for field in HEAT_LAYER_DEFINITIONS[record.layer_id]["canonical_fields"]
    ]
    return (
        *common_values,
        *canonical_values,
        artifact.run_id,
        layer_artifact.output_id,
        layer_artifact.generated_at,
        artifact.snapshot_id,
        artifact.release_commit,
        artifact.container_digest,
        record.source_feature_hash,
        published_at,
        record.geometry_json,
    )


def _sync_heat_layer(
    cursor: Any,
    *,
    table: str,
    layer_artifact: HeatLayerArtifact,
    artifact: HeatArtifact,
    published_at: datetime,
    stage_number: int,
) -> dict[str, int]:
    table = _identifier(table)
    layer_id = layer_artifact.layer_id
    definition = HEAT_LAYER_DEFINITIONS[layer_id]
    create_heat_table(cursor, table=table, layer_id=layer_id)
    columns = (
        *HEAT_COMMON_FIELDS,
        *definition["canonical_fields"],
        *PUBLICATION_COLUMNS,
    )
    column_list = ", ".join(columns)
    stage = f"heat_stage_{stage_number}"
    cursor.execute(
        f"CREATE TEMP TABLE {stage} (LIKE public.{table} INCLUDING DEFAULTS) ON COMMIT DROP"
    )
    if layer_artifact.records:
        template_factory = (
            values_template if definition["geometry"] == "multipolygon" else point_values_template
        )
        execute_values(
            cursor,
            f"INSERT INTO {stage} ({column_list}) VALUES %s",
            [
                heat_record_values(record, layer_artifact, artifact, published_at)
                for record in layer_artifact.records
            ],
            template=template_factory(len(columns) - 1),
            page_size=500,
        )
    update_columns = [name for name in columns if name not in {"feature_id", "geom"}]
    update_clause = ",\n                    ".join(
        f"{name} = EXCLUDED.{name}" for name in update_columns
    )
    cursor.execute(
        f"""
        INSERT INTO public.{table} AS current ({column_list})
        SELECT {column_list}
        FROM {stage}
        WHERE TRUE
        ON CONFLICT (feature_id) DO UPDATE SET
            {update_clause},
            geom = EXCLUDED.geom
        WHERE current.source_feature_hash IS DISTINCT FROM EXCLUDED.source_feature_hash
           OR current.release_commit IS DISTINCT FROM EXCLUDED.release_commit
           OR current.deployment_container_digest
                IS DISTINCT FROM EXCLUDED.deployment_container_digest
        """
    )
    changed = cursor.rowcount
    cursor.execute(
        f"""
        DELETE FROM public.{table} AS current
        WHERE NOT EXISTS (
            SELECT 1 FROM {stage}
            WHERE {stage}.feature_id = current.feature_id
        )
        """
    )
    deleted = cursor.rowcount
    cursor.execute(f"SELECT COUNT(*), COUNT(DISTINCT feature_id) FROM public.{table}")
    total, unique_ids = cursor.fetchone()
    if total != unique_ids or total != len(layer_artifact.records):
        raise RuntimeError(
            f"Heat publication mismatch for {layer_id}: source={len(layer_artifact.records)} "
            f"total={total} unique={unique_ids}"
        )
    return {"changed": changed, "deleted": deleted, "total": total}


def sync_heat_layers(
    db_conn: dict[str, Any],
    *,
    tables: dict[str, str],
    artifact: HeatArtifact,
) -> dict[str, dict[str, int]]:
    if set(tables) != set(HEAT_LAYER_DEFINITIONS):
        raise ValueError("Heat table configuration does not match the six-layer contract")
    published_at = datetime.now(timezone.utc)
    stats: dict[str, dict[str, int]] = {}
    with psycopg2.connect(**db_conn) as connection:
        with connection.cursor() as cursor:
            for index, layer_id in enumerate(HEAT_LAYER_DEFINITIONS):
                stats[layer_id] = _sync_heat_layer(
                    cursor,
                    table=tables[layer_id],
                    layer_artifact=artifact.layers[layer_id],
                    artifact=artifact,
                    published_at=published_at,
                    stage_number=index,
                )
    return stats
