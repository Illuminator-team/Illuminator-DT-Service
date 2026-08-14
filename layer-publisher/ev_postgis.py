import json
import re
from datetime import datetime, timezone
from typing import Any

import psycopg2
from ev import EV_FIELDS, EvRecord
from postgis_sql import point_values_template
from psycopg2.extras import Json, execute_values


IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,62}$")

EV_SQL_TYPES = {
    "feature_id": "TEXT PRIMARY KEY",
    "feature_uri": "TEXT UNIQUE NOT NULL",
    "source_feature_id": "TEXT UNIQUE NOT NULL",
    "address": "TEXT",
    "operator_name": "TEXT",
    "cpo_id": "TEXT",
    "reported_open": "BOOLEAN",
    "connector_count": "INTEGER NOT NULL CHECK (connector_count >= 0)",
    "available_connector_count": "INTEGER NOT NULL CHECK (available_connector_count >= 0)",
    "max_power_kw": "DOUBLE PRECISION CHECK (max_power_kw >= 0)",
    "connector_types": "JSONB NOT NULL",
    "power_types": "JSONB NOT NULL",
    "source_feature_modified_at": "TIMESTAMPTZ",
    "linked_connector_count": "INTEGER NOT NULL CHECK (linked_connector_count >= 0)",
    "unsupported_connector_count": "INTEGER NOT NULL CHECK (unsupported_connector_count >= 0)",
    "modeled_annual_energy_kwh": "DOUBLE PRECISION CHECK (modeled_annual_energy_kwh >= 0)",
    "modeled_annual_peak_kw": "DOUBLE PRECISION CHECK (modeled_annual_peak_kw >= 0)",
    "profile_available": "BOOLEAN NOT NULL",
    "profile_summary_kind": "TEXT",
    "datacompleetheid": "SMALLINT NOT NULL CHECK (datacompleetheid BETWEEN 0 AND 3)",
    "datacompleetheid_label": "TEXT NOT NULL",
    "datacompleetheid_method_version": "TEXT NOT NULL",
    "datacompleetheid_assessed_at": "TIMESTAMPTZ NOT NULL",
    "datacompleetheid_evidence": "JSONB NOT NULL",
    "completeness_reason": "TEXT NOT NULL",
    "model_id": "TEXT NOT NULL",
    "model_version": "TEXT NOT NULL",
    "metadata_contract_version": "TEXT NOT NULL",
    "release_commit": "CHAR(40) NOT NULL",
    "container_image": "TEXT NOT NULL",
    "model_run_at": "TIMESTAMPTZ NOT NULL",
    "output_generated_at": "TIMESTAMPTZ NOT NULL",
    "source_retrieved_at": "TIMESTAMPTZ NOT NULL",
    "output_id": "TEXT NOT NULL",
}

JSON_FIELDS = {
    "connector_types",
    "power_types",
    "datacompleetheid_evidence",
}


def _identifier(value: str) -> str:
    if not IDENTIFIER_PATTERN.fullmatch(value):
        raise ValueError(f"Unsafe PostGIS identifier: {value}")
    return value


def create_ev_table(cursor: Any, table: str) -> None:
    table = _identifier(table)
    definitions = ",\n            ".join(
        f"{name} {EV_SQL_TYPES[name]}" for name in EV_FIELDS
    )
    cursor.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS public.{table} (
            {definitions},
            source_feature_hash CHAR(64) NOT NULL,
            published_at TIMESTAMPTZ NOT NULL,
            geom geometry(Point, 4326) NOT NULL
        )
        """
    )
    cursor.execute(
        f"CREATE INDEX IF NOT EXISTS idx_{table}_geom ON public.{table} USING GIST (geom)"
    )


def ev_record_values(record: EvRecord, published_at: datetime) -> tuple[Any, ...]:
    values: list[Any] = []
    for field in EV_FIELDS:
        value = record.properties[field]
        if field in JSON_FIELDS:
            value = Json(
                value,
                dumps=lambda item: json.dumps(
                    item, ensure_ascii=True, separators=(",", ":")
                ),
            )
        values.append(value)
    return (*values, record.source_feature_hash, published_at, record.geometry_json)


def sync_ev_layer(
    db_conn: dict[str, Any],
    *,
    table: str,
    records: list[EvRecord],
) -> dict[str, int]:
    if not records:
        raise ValueError("EV publication requires at least one record")
    table = _identifier(table)
    published_at = datetime.now(timezone.utc)
    columns = (*EV_FIELDS, "source_feature_hash", "published_at", "geom")
    column_list = ", ".join(columns)
    update_columns = [name for name in columns if name not in {"feature_id", "geom"}]
    update_clause = ",\n                    ".join(
        f"{name} = EXCLUDED.{name}" for name in update_columns
    )

    with psycopg2.connect(**db_conn) as connection:
        with connection.cursor() as cursor:
            create_ev_table(cursor, table)
            stage_table = "ev_publication_stage"
            cursor.execute(
                f"CREATE TEMP TABLE {stage_table} "
                f"(LIKE public.{table} INCLUDING DEFAULTS) ON COMMIT DROP"
            )
            execute_values(
                cursor,
                f"INSERT INTO {stage_table} ({column_list}) VALUES %s",
                [ev_record_values(record, published_at) for record in records],
                template=point_values_template(len(columns) - 1),
                page_size=500,
            )
            cursor.execute(
                f"""
                INSERT INTO public.{table} AS current ({column_list})
                SELECT {column_list} FROM {stage_table}
                WHERE TRUE
                ON CONFLICT (feature_id) DO UPDATE SET
                    {update_clause},
                    geom = EXCLUDED.geom
                WHERE current.source_feature_hash IS DISTINCT FROM EXCLUDED.source_feature_hash
                """
            )
            changed = cursor.rowcount
            cursor.execute(
                f"""
                DELETE FROM public.{table} AS current
                WHERE NOT EXISTS (
                    SELECT 1 FROM {stage_table}
                    WHERE {stage_table}.feature_id = current.feature_id
                )
                """
            )
            deleted = cursor.rowcount
            cursor.execute(
                f"SELECT COUNT(*), COUNT(DISTINCT feature_id) FROM public.{table}"
            )
            total, unique_ids = cursor.fetchone()
    if total != unique_ids or total != len(records):
        raise RuntimeError(
            f"EV publication mismatch: source={len(records)} "
            f"total={total} unique={unique_ids}"
        )
    return {"changed": changed, "deleted": deleted, "total": total}
