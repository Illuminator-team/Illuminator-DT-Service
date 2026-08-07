import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urljoin, urlparse

import requests

PV_LAYER_ID = "pv_capacity"
PV_FIXTURE_CODE = "BU03610302"
PV_FIXTURE_NAME = "Overdie-Oost"
PV_MEDIA_TYPE = "application/geo+json"
PV_GEOMETRY_TYPES = {"Polygon", "MultiPolygon"}
PV_BUURT_CODE_PATTERN = re.compile(r"^BU[0-9]{8}$")
PV_FEATURE_URI_PREFIX = "https://reformers01.ewi.tudelft.nl/id/"
PV_QUALITY_FIELDS = (
    "datacompleetheid",
    "datacompleetheid_label",
    "datacompleetheid_method_version",
    "datacompleetheid_assessed_at",
    "datacompleetheid_observed",
    "datacompleetheid_estimated",
    "datacompleetheid_assumed",
    "datacompleetheid_missing",
    "completeness_reason",
)
PV_PROPERTY_FIELDS = (
    "feature_id",
    "feature_uri",
    "source_feature_id",
    "cbs_buurt_code",
    "buurt_name",
    "municipality",
    "pv_capacity_kwp",
    "pv_capacity_mwp",
    "residential_kwp_real",
    "commercial_kwp_derived",
    "capacity_kwp_combined",
    "capacity_method",
    "unit",
    "residential_input_status",
    *PV_QUALITY_FIELDS,
    "source_name",
    "source_reference_period",
    "source_modified_at",
    "source_retrieved_at",
    "source_last_updated",
    "model_run_at",
    "output_generated_at",
    "last_updated",
    "model_version",
    "metadata_contract_version",
)
PV_NUMERIC_FIELDS = (
    "pv_capacity_kwp",
    "pv_capacity_mwp",
    "residential_kwp_real",
    "commercial_kwp_derived",
    "capacity_kwp_combined",
)
PV_NULLABLE_FIELDS = {
    "source_modified_at",
    "source_retrieved_at",
    "source_last_updated",
}
PV_EMPTY_STRING_FIELDS = {
    "datacompleetheid_observed",
    "datacompleetheid_estimated",
    "datacompleetheid_assumed",
}


@dataclass(frozen=True)
class PvCapacityRecord:
    properties: dict[str, Any]
    source_feature_hash: str
    geometry_json: str

    @property
    def feature_id(self) -> str:
        return self.properties["feature_id"]

    @property
    def cbs_buurt_code(self) -> str:
        return self.properties["cbs_buurt_code"]


@dataclass(frozen=True)
class PvArtifact:
    records: list[PvCapacityRecord]
    release_commit: str
    container_image: str
    output_id: str
    output_generated_at: str
    cache_inventory_fingerprint: str


def _mapping(value: object, step: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{step} must be an object")
    return value


def _string(mapping: dict[str, Any], field: str, step: str) -> str:
    value = mapping.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{step}.{field} must be a non-empty string")
    return value


def _number(properties: dict[str, Any], field: str, feature_id: str) -> float:
    value = properties.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{feature_id}: {field} must be numeric")
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{feature_id}: {field} must be finite and non-negative")
    return value


def _timestamp(value: object, field: str, feature_id: str, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"{feature_id}: {field} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{feature_id}: {field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{feature_id}: {field} must include a timezone")
    return value


def _coordinate_pairs(value: object, feature_id: str) -> list[tuple[float, float]]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{feature_id}: geometry coordinates must be non-empty")
    if len(value) >= 2 and all(isinstance(item, (int, float)) for item in value[:2]):
        x, y = float(value[0]), float(value[1])
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError(f"{feature_id}: geometry coordinates must be finite")
        return [(x, y)]
    pairs: list[tuple[float, float]] = []
    for child in value:
        pairs.extend(_coordinate_pairs(child, feature_id))
    return pairs


def _validate_geometry(geometry: object, feature_id: str) -> dict[str, Any]:
    document = _mapping(geometry, f"{feature_id}.geometry")
    if document.get("type") not in PV_GEOMETRY_TYPES:
        raise ValueError(f"{feature_id}: geometry must be Polygon or MultiPolygon")
    for longitude, latitude in _coordinate_pairs(document.get("coordinates"), feature_id):
        if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
            raise ValueError(f"{feature_id}: geometry is not WGS84")
    return document


def _feature_hash(properties: dict[str, Any], geometry: dict[str, Any]) -> str:
    payload = {"properties": properties, "geometry": geometry}
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def load_pv_records(
    collection: object,
    *,
    expected_quality_method_version: str,
    expected_model_version: str,
    expected_metadata_contract_version: str,
) -> list[PvCapacityRecord]:
    document = _mapping(collection, "PV GeoJSON")
    if document.get("type") != "FeatureCollection":
        raise ValueError("PV output must be a GeoJSON FeatureCollection")
    features = document.get("features")
    if not isinstance(features, list) or not features:
        raise ValueError("PV output must contain features")

    records: list[PvCapacityRecord] = []
    feature_ids: set[str] = set()
    buurt_codes: set[str] = set()
    for feature in features:
        feature_document = _mapping(feature, "PV feature")
        properties = _mapping(feature_document.get("properties"), "PV feature properties")
        feature_id = _string(properties, "feature_id", "PV feature")
        buurt_code = _string(properties, "cbs_buurt_code", feature_id)
        if feature_id in feature_ids:
            raise ValueError(f"Duplicate PV feature_id: {feature_id}")
        if buurt_code in buurt_codes:
            raise ValueError(f"Duplicate PV cbs_buurt_code: {buurt_code}")

        normalized: dict[str, Any] = {}
        for field in PV_PROPERTY_FIELDS:
            value = properties.get(field)
            if field in PV_NUMERIC_FIELDS:
                value = _number(properties, field, feature_id)
            elif field == "datacompleetheid":
                if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 3:
                    raise ValueError(f"{feature_id}: datacompleetheid must be an integer from 0 to 3")
            elif field.endswith("_at") or field in {"source_last_updated", "last_updated"}:
                value = _timestamp(value, field, feature_id, field in PV_NULLABLE_FIELDS)
            elif value is None and field in PV_NULLABLE_FIELDS:
                pass
            elif not isinstance(value, str) or (
                not value and field not in PV_EMPTY_STRING_FIELDS
            ):
                raise ValueError(f"{feature_id}: {field} must be a non-empty string")
            normalized[field] = value

        if normalized["source_feature_id"] != buurt_code:
            raise ValueError(f"{feature_id}: source_feature_id must equal cbs_buurt_code")
        if not PV_BUURT_CODE_PATTERN.fullmatch(buurt_code):
            raise ValueError(f"{feature_id}: invalid CBS buurt code")
        if feature_id != f"pv_capacity_{buurt_code}":
            raise ValueError(f"{feature_id}: stable feature ID drift")
        if normalized["feature_uri"] != f"{PV_FEATURE_URI_PREFIX}{feature_id}":
            raise ValueError(f"{feature_id}: persistent feature URI drift")
        if normalized["capacity_method"] != "model_estimated" or normalized["unit"] != "kWp":
            raise ValueError(f"{feature_id}: PV capacity method or unit drift")
        if normalized["datacompleetheid_method_version"] != expected_quality_method_version:
            raise ValueError(f"{feature_id}: datacompleetheid method version drift")
        if normalized["model_version"] != expected_model_version:
            raise ValueError(f"{feature_id}: model version drift")
        if normalized["metadata_contract_version"] != expected_metadata_contract_version:
            raise ValueError(f"{feature_id}: metadata contract version drift")

        geometry = _validate_geometry(feature_document.get("geometry"), feature_id)
        records.append(
            PvCapacityRecord(
                properties=normalized,
                source_feature_hash=_feature_hash(normalized, geometry),
                geometry_json=json.dumps(geometry, ensure_ascii=True, separators=(",", ":")),
            )
        )
        feature_ids.add(feature_id)
        buurt_codes.add(buurt_code)

    fixtures = [record for record in records if record.cbs_buurt_code == PV_FIXTURE_CODE]
    if len(fixtures) != 1:
        raise ValueError(f"PV fixture {PV_FIXTURE_CODE} must occur exactly once")
    fixture = fixtures[0]
    if fixture.properties["buurt_name"] != PV_FIXTURE_NAME:
        raise ValueError("PV fixture buurt name drift")
    if fixture.properties["pv_capacity_kwp"] <= 0:
        raise ValueError("PV fixture capacity must be greater than zero")
    return records


def _request(
    session: Any,
    method: str,
    url: str,
    *,
    timeout: int,
    **kwargs: Any,
) -> Any:
    try:
        response = session.request(method, url, timeout=timeout, **kwargs)
        response.raise_for_status()
        return response
    except requests.RequestException as exc:
        raise RuntimeError(f"PV API request failed: {method} {urlparse(url).path}") from exc


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
        raise ValueError("PV output data link must remain on the configured API origin")
    return target


def _validate_identity(
    document: dict[str, Any],
    *,
    expected_release_commit: str,
    expected_container_image: str,
    step: str,
) -> None:
    if document.get("release_commit") != expected_release_commit:
        raise ValueError(f"{step}: release_commit drift")
    if document.get("container_image") != expected_container_image:
        raise ValueError(f"{step}: container_image drift")


def fetch_pv_artifact(
    base_url: str,
    *,
    expected_release_commit: str,
    expected_container_image: str,
    expected_model_version: str,
    expected_metadata_contract_version: str,
    session: Any = requests,
    timeout: int = 1800,
) -> PvArtifact:
    base_url = base_url.rstrip("/")
    readiness = _json_response(
        _request(session, "GET", f"{base_url}/ready", timeout=30),
        "GET /ready",
    )
    if readiness.get("ready") is not True or readiness.get("state") != "ready":
        raise RuntimeError("PV API is not ready")
    cache_fingerprint = _string(
        readiness, "cache_inventory_fingerprint", "GET /ready"
    )

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
    if metadata.get("capacity_method") != "model_estimated":
        raise ValueError("GET /metadata: capacity method drift")
    if metadata.get("model_version") != expected_model_version:
        raise ValueError("GET /metadata: model version drift")
    if metadata.get("metadata_contract_version") != expected_metadata_contract_version:
        raise ValueError("GET /metadata: metadata contract version drift")

    layers = _json_response(
        _request(session, "GET", f"{base_url}/layers", timeout=30),
        "GET /layers",
    )
    layer_records = layers.get("layers")
    if not isinstance(layer_records, list) or len(layer_records) != 1:
        raise ValueError("GET /layers must expose exactly one PV layer")
    layer = _mapping(layer_records[0], "GET /layers layer")
    if layer.get("layer_id") != PV_LAYER_ID or layer.get("crs") != "EPSG:4326":
        raise ValueError("GET /layers: PV layer identity or CRS drift")
    if layer.get("model_version") != expected_model_version:
        raise ValueError("GET /layers: model version drift")
    if layer.get("metadata_contract_version") != expected_metadata_contract_version:
        raise ValueError("GET /layers: metadata contract version drift")
    attributes = layer.get("attributes")
    if not isinstance(attributes, list):
        raise TypeError("GET /layers: attributes are missing")
    value_fields = {item.get("name"): item for item in attributes if isinstance(item, dict)}
    if value_fields.get("pv_capacity_kwp", {}).get("unit") != "kWp":
        raise ValueError("GET /layers: pv_capacity_kwp unit drift")
    quality = _mapping(layer.get("datacompleetheid"), "GET /layers datacompleetheid")
    quality_method = _string(quality, "method_version", "GET /layers datacompleetheid")

    run = _json_response(
        _request(
            session,
            "POST",
            f"{base_url}/runs",
            timeout=timeout,
            json={"spatial_selection": {"type": "all"}, "parameters": {}},
        ),
        "POST /runs",
    )
    _validate_identity(
        run,
        expected_release_commit=expected_release_commit,
        expected_container_image=expected_container_image,
        step="POST /runs",
    )
    if run.get("status") != "succeeded":
        raise RuntimeError("POST /runs did not succeed")
    run_id = _string(run, "run_id", "POST /runs")
    output_ids = run.get("output_ids")
    if not isinstance(output_ids, list) or len(output_ids) != 1:
        raise ValueError("POST /runs must return exactly one output ID")
    output_id = output_ids[0]
    if not isinstance(output_id, str) or not output_id:
        raise ValueError("POST /runs returned an invalid output ID")

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
    if output.get("layer_id") != PV_LAYER_ID or output.get("media_type") != PV_MEDIA_TYPE:
        raise ValueError("GET output: layer or media type drift")
    if output.get("model_version") != expected_model_version:
        raise ValueError("GET output: model version drift")
    if output.get("metadata_contract_version") != expected_metadata_contract_version:
        raise ValueError("GET output: metadata contract version drift")
    if output.get("datacompleetheid_method_version") != quality_method:
        raise ValueError("GET output: datacompleetheid method version drift")
    links = _mapping(output.get("links"), "GET output links")
    data_url = _same_origin_url(base_url, _string(links, "data", "GET output links"))
    data_response = _request(session, "GET", data_url, timeout=timeout)
    content = data_response.content
    if len(content) != output.get("byte_size"):
        raise ValueError("PV output byte size does not match its record")
    if hashlib.sha256(content).hexdigest() != output.get("sha256"):
        raise ValueError("PV output SHA-256 does not match its record")
    if data_response.headers.get("content-type", "").split(";", 1)[0] != PV_MEDIA_TYPE:
        raise ValueError("PV output response media type drift")
    try:
        collection = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("PV output is not valid UTF-8 GeoJSON") from exc
    records = load_pv_records(
        collection,
        expected_quality_method_version=quality_method,
        expected_model_version=expected_model_version,
        expected_metadata_contract_version=expected_metadata_contract_version,
    )
    if len(records) != output.get("feature_count"):
        raise ValueError("PV output feature count does not match its record")

    return PvArtifact(
        records=records,
        release_commit=expected_release_commit,
        container_image=expected_container_image,
        output_id=output_id,
        output_generated_at=_string(output, "output_generated_at", "GET output"),
        cache_inventory_fingerprint=cache_fingerprint,
    )


def get_pv_readiness_signature(
    base_url: str,
    *,
    session: Any = requests,
) -> tuple[str, str]:
    response = _json_response(
        _request(session, "GET", f"{base_url.rstrip('/')}/ready", timeout=30),
        "GET /ready",
    )
    if response.get("ready") is not True or response.get("state") != "ready":
        raise RuntimeError("PV API is not ready")
    return (
        _string(response, "cache_inventory_fingerprint", "GET /ready"),
        _string(response, "finished_at", "GET /ready"),
    )
