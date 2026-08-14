import json
from datetime import datetime, timezone
from typing import Any

import psycopg2
from consumption import CONSUMPTION_FIELDS, ConsumptionRecord
from ev import EV_FIELDS, EvRecord
from postgis_sql import point_values_template, values_template
from psycopg2.extras import Json, execute_values


CONSUMPTION_SQL_TYPES = {
    "feature_id": "TEXT PRIMARY KEY",
    "feature_uri": "TEXT UNIQUE NOT NULL",
    "spatial_unit_type": "TEXT NOT NULL",
    "spatial_unit_code": "TEXT NOT NULL",
    "name": "TEXT NOT NULL",
    "annual_electricity_consumption_kwh": "DOUBLE PRECISION NOT NULL CHECK (annual_electricity_consumption_kwh >= 0)",
    "annual_electricity_kwh": "DOUBLE PRECISION NOT NULL CHECK (annual_electricity_kwh >= 0)",
    "residential_electricity_kwh": "DOUBLE PRECISION CHECK (residential_electricity_kwh >= 0)",
    "business_electricity_kwh": "DOUBLE PRECISION CHECK (business_electricity_kwh >= 0)",
    "services_commerce_electricity_kwh": "DOUBLE PRECISION CHECK (services_commerce_electricity_kwh >= 0)",
    "unknown_industrial_business_electricity_kwh": "DOUBLE PRECISION CHECK (unknown_industrial_business_electricity_kwh >= 0)",
    "unknown_business_electricity_kwh": "DOUBLE PRECISION CHECK (unknown_business_electricity_kwh >= 0)",
    "annual_value_status": "TEXT NOT NULL",
    "residential_value_status": "TEXT NOT NULL",
    "business_value_status": "TEXT NOT NULL",
    "allocation_method": "TEXT NOT NULL",
    "source_reference_period": "TEXT NOT NULL",
    "source_modified_at": "TIMESTAMPTZ",
    "source_modified_at_status": "TEXT NOT NULL",
    "source_retrieved_at": "TIMESTAMPTZ",
    "source_retrieved_at_status": "TEXT NOT NULL",
    "source_retrieved_on": "DATE NOT NULL",
    "source_ids": "JSONB NOT NULL",
    "sources": "JSONB NOT NULL",
    "quality_flags": "JSONB NOT NULL",
    "datacompleetheid": "SMALLINT NOT NULL CHECK (datacompleetheid BETWEEN 0 AND 3)",
    "datacompleetheid_label": "TEXT NOT NULL",
    "datacompleetheid_rule_version": "TEXT NOT NULL",
    "datacompleetheid_assessed_at": "TIMESTAMPTZ NOT NULL",
    "datacompleetheid_evidence": "JSONB NOT NULL",
    "datacompleetheid_reason_codes": "JSONB NOT NULL",
    "datacompleetheid_explanation": "TEXT NOT NULL",
    "model_run_at": "TIMESTAMPTZ NOT NULL",
    "output_generated_at": "TIMESTAMPTZ NOT NULL",
    "model_version": "TEXT NOT NULL",
    "metadata_contract_version": "TEXT NOT NULL",
    "release_commit": "CHAR(40) NOT NULL",
    "container_image": "TEXT NOT NULL",
    "provenance": "JSONB NOT NULL",
}

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

MODEL_LAYER_SQL = {
    "electricity_consumption_areas": {
        "fields": CONSUMPTION_FIELDS,
        "types": CONSUMPTION_SQL_TYPES,
        "geometry_type": "MultiPolygon",
        "template": values_template,
        "json_fields": {
            "source_ids",
            "sources",
            "quality_flags",
            "datacompleetheid_evidence",
            "datacompleetheid_reason_codes",
            "provenance",
        },
    },
    "public_ev_chargers": {
        "fields": EV_FIELDS,
        "types": EV_SQL_TYPES,
        "geometry_type": "Point",
        "template": point_values_template,
        "json_fields": {"connector_types", "power_types", "datacompleetheid_evidence"},
    },
}


def create_model_table(cursor: Any, table: str, layer_id: str) -> None:
    config = MODEL_LAYER_SQL[layer_id]
    definitions = ",\n            ".join(
        f"{name} {config['types'][name]}" for name in config["fields"]
    )
    cursor.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS public.{table} (
            {definitions},
            source_feature_hash CHAR(64) NOT NULL,
            published_at TIMESTAMPTZ NOT NULL,
            geom geometry({config['geometry_type']}, 4326) NOT NULL
        )
        """
    )
    cursor.execute(
        f"CREATE INDEX IF NOT EXISTS idx_{table}_geom ON public.{table} USING GIST (geom)"
    )


def model_record_values(
    record: ConsumptionRecord | EvRecord,
    *,
    layer_id: str,
    published_at: datetime,
) -> tuple[Any, ...]:
    config = MODEL_LAYER_SQL[layer_id]
    values: list[Any] = []
    for field in config["fields"]:
        value = record.properties[field]
        if field in config["json_fields"]:
            value = Json(value, dumps=lambda item: json.dumps(item, separators=(",", ":")))
        values.append(value)
    return (*values, record.source_feature_hash, published_at, record.geometry_json)


def sync_model_layer(
    db_conn: dict[str, Any],
    *,
    table: str,
    layer_id: str,
    records: list[ConsumptionRecord] | list[EvRecord],
) -> dict[str, int]:
    if not records:
        raise ValueError(f"{layer_id} publication requires at least one record")
    config = MODEL_LAYER_SQL[layer_id]
    published_at = datetime.now(timezone.utc)
    columns = (*config["fields"], "source_feature_hash", "published_at", "geom")
    column_list = ", ".join(columns)
    update_columns = [name for name in columns if name not in {"feature_id", "geom"}]
    update_clause = ",\n                    ".join(
        f"{name} = EXCLUDED.{name}" for name in update_columns
    )

    with psycopg2.connect(**db_conn) as connection:
        with connection.cursor() as cursor:
            create_model_table(cursor, table, layer_id)
            stage_table = f"{table}_stage"
            cursor.execute(
                f"CREATE TEMP TABLE {stage_table} (LIKE public.{table} INCLUDING DEFAULTS) ON COMMIT DROP"
            )
            execute_values(
                cursor,
                f"INSERT INTO {stage_table} ({column_list}) VALUES %s",
                [
                    model_record_values(record, layer_id=layer_id, published_at=published_at)
                    for record in records
                ],
                template=config["template"](len(columns) - 1),
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
            f"{layer_id} publication mismatch: source={len(records)} total={total} unique={unique_ids}"
        )
    return {"changed": changed, "deleted": deleted, "total": total}
