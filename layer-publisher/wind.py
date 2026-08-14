import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urljoin, urlparse
from uuid import UUID

import requests

WIND_LAYER_ID = "public_wind_turbines"
WIND_MODEL_ID = "https://reformers01.ewi.tudelft.nl/id/model/wind-turbine-map"
WIND_MEDIA_TYPE = "application/geo+json"
WIND_QUALITY_METHOD = "WIND-DATA-COMPLETE-001"
WIND_FEATURE_PATTERN = re.compile(r"^wind-turbine-[0-9]+$")
WIND_FEATURE_URI_PREFIX = "https://reformers01.ewi.tudelft.nl/id/wind-turbine/"
WIND_STABLE_FIXTURE = "wind-turbine-2811"

WIND_PROPERTY_FIELDS = (
    "feature_id",
    "persistent_uri",
    "source_feature_id",
    "capacity_kw",
    "capacity_unit",
    "capacity_mw",
    "capacity_mw_unit",
    "hub_height_m",
    "hub_height_unit",
    "rotor_diameter_m",
    "rotor_diameter_unit",
    "tip_height_m",
    "tip_height_unit",
    "rotor_swept_area_m2",
    "rotor_swept_area_unit",
    "name",
    "turbine_type",
    "municipality",
    "province",
    "country",
    "surface",
    "source_reference_date",
    "modeled_annual_energy_kwh",
    "modeled_annual_energy_unit",
    "modeled_capacity_factor",
    "modeled_peak_power_kw",
    "modeled_peak_power_unit",
    "modeled_profile_year",
    "modeled_profile_interval",
    "profile_id",
    "profile_transport_available",
    "inventory_evidence_status",
    "geometry_evidence_status",
    "capacity_evidence_status",
    "derived_geometry_status",
    "generation_evidence_status",
    "quality_flags",
    "datacompleetheid",
    "datacompleetheid_label",
    "datacompleetheid_rule_version",
    "datacompleetheid_assessed_at",
    "datacompleetheid_reason_codes",
    "datacompleetheid_evidence",
    "completeness_reason",
    "source_reference_period",
    "source_modified_at",
    "source_last_updated",
    "source_retrieved_at",
    "source_evidence",
    "limitations",
    "data_mode",
    "model_id",
    "model_version",
    "contract_version",
    "schema_contract_version",
    "git_commit",
    "container_image",
    "model_run_at",
    "output_generated_at",
    "run_id",
    "output_id",
)

WIND_NUMERIC_FIELDS = {
    "capacity_kw",
    "capacity_mw",
    "hub_height_m",
    "rotor_diameter_m",
    "tip_height_m",
    "rotor_swept_area_m2",
    "modeled_annual_energy_kwh",
    "modeled_capacity_factor",
    "modeled_peak_power_kw",
}
WIND_NULLABLE_FIELDS = {
    "capacity_kw",
    "capacity_mw",
    "hub_height_m",
    "rotor_diameter_m",
    "tip_height_m",
    "rotor_swept_area_m2",
    "name",
    "turbine_type",
    "modeled_annual_energy_kwh",
    "modeled_capacity_factor",
    "modeled_peak_power_kw",
    "modeled_profile_year",
    "modeled_profile_interval",
    "profile_id",
    "source_reference_period",
    "source_modified_at",
    "source_last_updated",
    "source_retrieved_at",
}
WIND_TIMESTAMP_FIELDS = {
    "datacompleetheid_assessed_at",
    "source_modified_at",
    "source_last_updated",
    "source_retrieved_at",
    "model_run_at",
    "output_generated_at",
}
WIND_JSON_FIELDS = {
    "quality_flags",
    "datacompleetheid_reason_codes",
    "datacompleetheid_evidence",
    "source_evidence",
    "limitations",
}
WIND_VOLATILE_FIELDS = {
    "datacompleetheid_assessed_at",
    "model_run_at",
    "output_generated_at",
    "run_id",
    "output_id",
}


@dataclass(frozen=True)
class WindRecord:
    properties: dict[str, Any]
    source_feature_hash: str
    geometry_json: str

    @property
    def feature_id(self) -> str:
        return self.properties["feature_id"]


@dataclass(frozen=True)
class WindArtifact:
    records: list[WindRecord]
    release_commit: str
    container_image: str
    container_digest: str
    output_id: str
    output_generated_at: str
    initialized_at: str
    data_mode: str


def _mapping(value: object, step: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{step} must be an object")
    return value


def _string(mapping: dict[str, Any], field: str, step: str) -> str:
    value = mapping.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{step}.{field} must be a non-empty string")
    return value


def _timestamp(value: object, field: str, feature_id: str, nullable: bool) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"{feature_id}: {field} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{feature_id}: {field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{feature_id}: {field} must include a timezone")
    return value


def _number(value: object, field: str, feature_id: str, nullable: bool) -> float | None:
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{feature_id}: {field} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0:
        raise ValueError(f"{feature_id}: {field} must be finite and non-negative")
    return normalized


def _uuid(value: object, field: str, feature_id: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{feature_id}: {field} must be a UUID string")
    try:
        UUID(value)
    except ValueError as exc:
        raise ValueError(f"{feature_id}: {field} must be a UUID string") from exc
    return value


def _validate_geometry(value: object, feature_id: str) -> dict[str, Any]:
    geometry = _mapping(value, f"{feature_id}.geometry")
    coordinates = geometry.get("coordinates")
    if set(geometry) != {"type", "coordinates"}:
        raise ValueError(f"{feature_id}: geometry contract drift")
    if (
        geometry.get("type") != "Point"
        or not isinstance(coordinates, list)
        or len(coordinates) != 2
    ):
        raise ValueError(f"{feature_id}: geometry must be a Point")
    longitude, latitude = coordinates[:2]
    if any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in (longitude, latitude)):
        raise TypeError(f"{feature_id}: point coordinates must be numeric")
    if not math.isfinite(float(longitude)) or not math.isfinite(float(latitude)):
        raise ValueError(f"{feature_id}: point coordinates must be finite")
    if not -180 <= float(longitude) <= 180 or not -90 <= float(latitude) <= 90:
        raise ValueError(f"{feature_id}: point geometry is not WGS84")
    return geometry


def _feature_hash(properties: dict[str, Any], geometry: dict[str, Any]) -> str:
    stable_properties = {
        field: value
        for field, value in properties.items()
        if field not in WIND_VOLATILE_FIELDS
    }
    encoded = json.dumps(
        {"properties": stable_properties, "geometry": geometry},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def load_wind_records(
    collection: object,
    *,
    expected_release_commit: str,
    expected_container_image: str,
    expected_model_version: str,
    expected_contract_version: str,
    expected_schema_contract_version: str,
    expected_data_mode: str,
) -> list[WindRecord]:
    document = _mapping(collection, "Wind GeoJSON")
    if set(document) != {"type", "features"}:
        raise ValueError("Wind output collection contract drift")
    if document.get("type") != "FeatureCollection":
        raise ValueError("Wind output must be a GeoJSON FeatureCollection")
    features = document.get("features")
    if not isinstance(features, list) or not features:
        raise ValueError("Wind output must contain features")

    records: list[WindRecord] = []
    feature_ids: set[str] = set()
    expected_fields = set(WIND_PROPERTY_FIELDS)
    for feature in features:
        item = _mapping(feature, "Wind feature")
        if (
            set(item) != {"type", "id", "geometry", "properties"}
            or item.get("type") != "Feature"
        ):
            raise ValueError("Wind feature contract drift")
        properties = _mapping(item.get("properties"), "Wind feature properties")
        if set(properties) != expected_fields:
            missing = sorted(expected_fields - set(properties))
            extra = sorted(set(properties) - expected_fields)
            raise ValueError(f"Wind feature property contract drift: missing={missing} extra={extra}")
        feature_id = _string(properties, "feature_id", "Wind feature")
        if feature_id in feature_ids:
            raise ValueError(f"Duplicate Wind feature_id: {feature_id}")
        if not WIND_FEATURE_PATTERN.fullmatch(feature_id):
            raise ValueError(f"{feature_id}: stable feature ID drift")
        if item.get("id") != feature_id:
            raise ValueError(f"{feature_id}: GeoJSON id must equal feature_id")
        if properties["persistent_uri"] != f"{WIND_FEATURE_URI_PREFIX}{feature_id}":
            raise ValueError(f"{feature_id}: persistent feature URI drift")

        normalized: dict[str, Any] = {}
        for field in WIND_PROPERTY_FIELDS:
            value = properties[field]
            if field in WIND_NUMERIC_FIELDS:
                value = _number(value, field, feature_id, field in WIND_NULLABLE_FIELDS)
            elif field in WIND_TIMESTAMP_FIELDS:
                value = _timestamp(value, field, feature_id, field in WIND_NULLABLE_FIELDS)
            elif field in WIND_JSON_FIELDS:
                if field in {"source_evidence", "datacompleetheid_evidence"}:
                    if not isinstance(value, dict):
                        raise TypeError(f"{feature_id}: {field} must be an object")
                elif not isinstance(value, list):
                    raise TypeError(f"{feature_id}: {field} must be an array")
            elif field == "profile_transport_available":
                if value is not False:
                    raise ValueError(f"{feature_id}: profile transport must remain unavailable in phase 1")
            elif field in {"run_id", "output_id"}:
                value = _uuid(value, field, feature_id)
            elif field in {"datacompleetheid", "modeled_profile_year"}:
                if value is None and field in WIND_NULLABLE_FIELDS:
                    pass
                elif isinstance(value, bool) or not isinstance(value, int):
                    raise TypeError(f"{feature_id}: {field} must be an integer")
            elif value is None and field in WIND_NULLABLE_FIELDS:
                pass
            elif not isinstance(value, str) or not value:
                raise ValueError(f"{feature_id}: {field} must be a non-empty string")
            normalized[field] = value

        if not 0 <= normalized["datacompleetheid"] <= 3:
            raise ValueError(f"{feature_id}: datacompleetheid must be from 0 to 3")
        if normalized["modeled_capacity_factor"] is not None and normalized["modeled_capacity_factor"] > 1:
            raise ValueError(f"{feature_id}: modeled_capacity_factor must be from 0 to 1")
        if normalized["capacity_unit"] != "kW" or normalized["capacity_mw_unit"] != "MW":
            raise ValueError(f"{feature_id}: capacity unit drift")
        if any(
            normalized[field] != expected
            for field, expected in {
                "hub_height_unit": "m",
                "rotor_diameter_unit": "m",
                "tip_height_unit": "m",
                "rotor_swept_area_unit": "m2",
                "modeled_annual_energy_unit": "kWh",
                "modeled_peak_power_unit": "kW",
            }.items()
        ):
            raise ValueError(f"{feature_id}: measurement unit drift")
        if normalized["modeled_profile_interval"] not in {None, "PT15M"}:
            raise ValueError(f"{feature_id}: profile interval drift")
        if normalized["modeled_profile_year"] not in {None, 2025}:
            raise ValueError(f"{feature_id}: profile year drift")
        if normalized["datacompleetheid_rule_version"] != WIND_QUALITY_METHOD:
            raise ValueError(f"{feature_id}: datacompleetheid method drift")
        if normalized["inventory_evidence_status"] != "published_inventory":
            raise ValueError(f"{feature_id}: inventory evidence status drift")
        if normalized["generation_evidence_status"] not in {
            "provisional_model_estimate",
            "not_available",
        }:
            raise ValueError(f"{feature_id}: generation evidence status drift")
        if normalized["model_id"] != WIND_MODEL_ID:
            raise ValueError(f"{feature_id}: model ID drift")
        if normalized["model_version"] != expected_model_version:
            raise ValueError(f"{feature_id}: model version drift")
        if normalized["contract_version"] != expected_contract_version:
            raise ValueError(f"{feature_id}: contract version drift")
        if normalized["schema_contract_version"] != expected_schema_contract_version:
            raise ValueError(f"{feature_id}: schema contract version drift")
        if normalized["git_commit"] != expected_release_commit:
            raise ValueError(f"{feature_id}: release commit drift")
        if normalized["container_image"] != expected_container_image:
            raise ValueError(f"{feature_id}: container image identity drift")
        if normalized["data_mode"] != expected_data_mode:
            raise ValueError(f"{feature_id}: data mode drift")

        geometry = _validate_geometry(item.get("geometry"), feature_id)
        records.append(
            WindRecord(
                properties=normalized,
                source_feature_hash=_feature_hash(normalized, geometry),
                geometry_json=json.dumps(geometry, ensure_ascii=True, separators=(",", ":")),
            )
        )
        feature_ids.add(feature_id)

    fixture = next((record for record in records if record.feature_id == WIND_STABLE_FIXTURE), None)
    if fixture is None:
        raise ValueError(f"Wind stable fixture {WIND_STABLE_FIXTURE} is missing")
    if not fixture.properties["capacity_kw"] or fixture.properties["capacity_kw"] <= 0:
        raise ValueError("Wind stable fixture capacity must be greater than zero")
    return records


def _request(session: Any, method: str, url: str, *, timeout: int, **kwargs: Any) -> Any:
    try:
        response = session.request(method, url, timeout=timeout, **kwargs)
        response.raise_for_status()
        return response
    except requests.RequestException as exc:
        raise RuntimeError(f"Wind API request failed: {method} {urlparse(url).path}") from exc


def _json_response(response: Any, step: str) -> dict[str, Any]:
    try:
        return _mapping(response.json(), step)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"{step} did not return a JSON object") from exc


def _same_origin_url(base_url: str, path: str) -> str:
    target = urljoin(f"{base_url.rstrip('/')}/", path.lstrip("/"))
    base = urlparse(base_url)
    parsed = urlparse(target)
    if parsed.scheme != base.scheme or parsed.netloc != base.netloc:
        raise ValueError("Wind output data link must remain on the configured API origin")
    return target


def _validate_identity(
    document: dict[str, Any],
    *,
    expected_release_commit: str,
    expected_container_image: str,
    step: str,
) -> None:
    if document.get("git_commit") != expected_release_commit:
        raise ValueError(f"{step}: git_commit drift")
    if document.get("container_image") != expected_container_image:
        raise ValueError(f"{step}: container_image drift")


def get_wind_readiness_signature(
    base_url: str,
    *,
    expected_data_mode: str | None = None,
    session: Any = requests,
) -> tuple[str, str, int, str, str]:
    document = _json_response(
        _request(session, "GET", f"{base_url.rstrip('/')}/ready", timeout=30),
        "GET /ready",
    )
    if document.get("ready") is not True or document.get("state") != "ready":
        raise RuntimeError("Wind API is not ready")
    data_mode = _string(document, "data_mode", "GET /ready")
    if expected_data_mode and data_mode != expected_data_mode:
        raise ValueError("GET /ready: data mode drift")
    feature_count = document.get("feature_count")
    if isinstance(feature_count, bool) or not isinstance(feature_count, int) or feature_count < 1:
        raise ValueError("GET /ready: feature_count must be positive")
    return (
        data_mode,
        _string(document, "initialized_at", "GET /ready"),
        feature_count,
        _string(document, "model_version", "GET /ready"),
        _string(document, "contract_version", "GET /ready"),
    )


def fetch_wind_artifact(
    base_url: str,
    *,
    expected_release_commit: str,
    expected_container_image: str,
    expected_container_digest: str,
    expected_model_version: str,
    expected_contract_version: str,
    expected_schema_contract_version: str,
    expected_data_mode: str,
    session: Any = requests,
    timeout: int = 300,
) -> WindArtifact:
    base_url = base_url.rstrip("/")
    signature = get_wind_readiness_signature(
        base_url,
        expected_data_mode=expected_data_mode,
        session=session,
    )
    if signature[3:] != (expected_model_version, expected_contract_version):
        raise ValueError("GET /ready: model or contract version drift")

    metadata = _json_response(
        _request(session, "GET", f"{base_url}/metadata", timeout=30),
        "GET /metadata",
    )
    _validate_identity(
        metadata,
        expected_release_commit=expected_release_commit,
        expected_container_image=expected_container_image,
        step="GET /metadata",
    )
    model = _mapping(metadata.get("model"), "GET /metadata model")
    if model.get("id") != WIND_MODEL_ID or model.get("version") != expected_model_version:
        raise ValueError("GET /metadata: model identity drift")
    if metadata.get("contract_version") != expected_contract_version:
        raise ValueError("GET /metadata: contract version drift")
    if metadata.get("schema_contract_version") != expected_schema_contract_version:
        raise ValueError("GET /metadata: schema contract version drift")
    if metadata.get("crs", {}).get("output") != "OGC:CRS84":
        raise ValueError("GET /metadata: CRS drift")

    layers = _json_response(
        _request(session, "GET", f"{base_url}/layers", timeout=30),
        "GET /layers",
    )
    layer_records = layers.get("layers")
    if not isinstance(layer_records, list) or len(layer_records) != 1:
        raise ValueError("GET /layers must expose exactly one Wind layer")
    layer = _mapping(layer_records[0], "GET /layers layer")
    if layer.get("id") != WIND_LAYER_ID or layer.get("geometry_type") != "Point":
        raise ValueError("GET /layers: Wind layer identity or geometry drift")
    expected_feature_count = layer.get("expected_feature_count")
    runtime = _mapping(layer.get("runtime"), "GET /layers runtime")
    if runtime.get("data_mode") != expected_data_mode:
        raise ValueError("GET /layers: runtime data mode drift")
    if runtime.get("feature_count") != signature[2] or expected_feature_count != signature[2]:
        raise ValueError("GET /layers: feature count drift")

    run = _json_response(
        _request(
            session,
            "POST",
            f"{base_url}/runs",
            timeout=timeout,
            json={
                "layer_id": WIND_LAYER_ID,
                "spatial_selection": {"type": "all"},
                "parameters": {},
            },
        ),
        "POST /runs",
    )
    _validate_identity(
        run,
        expected_release_commit=expected_release_commit,
        expected_container_image=expected_container_image,
        step="POST /runs",
    )
    if run.get("status") != "completed":
        raise RuntimeError("POST /runs did not complete")
    run_id = _string(run, "run_id", "POST /runs")
    outputs = run.get("outputs")
    if not isinstance(outputs, list) or len(outputs) != 1:
        raise ValueError("POST /runs must return exactly one output")
    output_id = _string(_mapping(outputs[0], "POST /runs output"), "output_id", "POST /runs output")

    stored_run = _json_response(
        _request(session, "GET", f"{base_url}/runs/{run_id}", timeout=30),
        "GET run",
    )
    if stored_run != run:
        raise ValueError("GET run does not match the completed run record")

    output = _json_response(
        _request(session, "GET", f"{base_url}/outputs/{output_id}", timeout=30),
        "GET output",
    )
    _validate_identity(
        output,
        expected_release_commit=expected_release_commit,
        expected_container_image=expected_container_image,
        step="GET output",
    )
    if output.get("layer_id") != WIND_LAYER_ID or output.get("media_type") != WIND_MEDIA_TYPE:
        raise ValueError("GET output: layer or media type drift")
    if output.get("model_version") != expected_model_version:
        raise ValueError("GET output: model version drift")
    if output.get("schema_contract_version") != expected_schema_contract_version:
        raise ValueError("GET output: schema contract version drift")
    if output.get("data_mode") != expected_data_mode:
        raise ValueError("GET output: data mode drift")
    links = _mapping(output.get("links"), "GET output links")
    data_url = _same_origin_url(base_url, _string(links, "data", "GET output links"))
    response = _request(session, "GET", data_url, timeout=timeout)
    content = response.content
    if len(content) != output.get("byte_size"):
        raise ValueError("Wind output byte size does not match its record")
    if hashlib.sha256(content).hexdigest() != output.get("sha256"):
        raise ValueError("Wind output checksum does not match its record")
    if not response.headers.get("content-type", "").startswith(WIND_MEDIA_TYPE):
        raise ValueError("Wind output media type header drift")
    try:
        collection = json.loads(content)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("Wind output data is not valid JSON") from exc

    records = load_wind_records(
        collection,
        expected_release_commit=expected_release_commit,
        expected_container_image=expected_container_image,
        expected_model_version=expected_model_version,
        expected_contract_version=expected_contract_version,
        expected_schema_contract_version=expected_schema_contract_version,
        expected_data_mode=expected_data_mode,
    )
    if len(records) != signature[2] or len(records) != output.get("feature_count"):
        raise ValueError("Wind output feature count does not match readiness/output records")
    return WindArtifact(
        records=records,
        release_commit=expected_release_commit,
        container_image=expected_container_image,
        container_digest=expected_container_digest,
        output_id=output_id,
        output_generated_at=_string(output, "output_generated_at", "GET output"),
        initialized_at=signature[1],
        data_mode=expected_data_mode,
    )
