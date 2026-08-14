import hashlib
import json
import math
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urljoin, urlparse

import requests


CONSUMPTION_LAYER_ID = "electricity_consumption_areas"
CONSUMPTION_MEDIA_TYPE = "application/geo+json"
CONSUMPTION_FIELDS = (
    "feature_id",
    "feature_uri",
    "spatial_unit_type",
    "spatial_unit_code",
    "name",
    "annual_electricity_consumption_kwh",
    "annual_electricity_kwh",
    "residential_electricity_kwh",
    "business_electricity_kwh",
    "services_commerce_electricity_kwh",
    "unknown_industrial_business_electricity_kwh",
    "unknown_business_electricity_kwh",
    "annual_value_status",
    "residential_value_status",
    "business_value_status",
    "allocation_method",
    "source_reference_period",
    "source_modified_at",
    "source_modified_at_status",
    "source_retrieved_at",
    "source_retrieved_at_status",
    "source_retrieved_on",
    "source_ids",
    "sources",
    "quality_flags",
    "datacompleetheid",
    "datacompleetheid_label",
    "datacompleetheid_rule_version",
    "datacompleetheid_assessed_at",
    "datacompleetheid_evidence",
    "datacompleetheid_reason_codes",
    "datacompleetheid_explanation",
    "model_run_at",
    "output_generated_at",
    "model_version",
    "metadata_contract_version",
    "release_commit",
    "container_image",
    "provenance",
)
CONSUMPTION_RUN_FIELDS = {
    "model_run_at",
    "output_generated_at",
    "datacompleetheid_assessed_at",
}


@dataclass(frozen=True)
class ConsumptionRecord:
    properties: dict[str, Any]
    geometry_json: str
    source_feature_hash: str


@dataclass(frozen=True)
class ConsumptionArtifact:
    records: list[ConsumptionRecord]
    release_commit: str
    container_image: str
    output_id: str
    output_generated_at: str
    state_fingerprint: str


def _mapping(value: object, step: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{step} must be an object")
    return value


def _string(mapping: dict[str, Any], field: str, step: str) -> str:
    value = mapping.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{step}: {field} must be a non-empty string")
    return value


def _timestamp(value: object, field: str, feature_id: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"{feature_id}: {field} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{feature_id}: {field} must be an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{feature_id}: {field} must include a timezone")
    return value


def _nonnegative_number(
    properties: dict[str, Any], field: str, feature_id: str, *, nullable: bool = False
) -> float | None:
    value = properties.get(field)
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{feature_id}: {field} must be numeric")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{feature_id}: {field} must be finite and non-negative")
    return number


def _coordinate_pairs(value: object, feature_id: str) -> list[tuple[float, float]]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{feature_id}: geometry coordinates are empty")
    if len(value) >= 2 and all(isinstance(item, (int, float)) for item in value[:2]):
        lon, lat = float(value[0]), float(value[1])
        if not math.isfinite(lon) or not math.isfinite(lat):
            raise ValueError(f"{feature_id}: geometry contains non-finite coordinates")
        return [(lon, lat)]
    result: list[tuple[float, float]] = []
    for child in value:
        result.extend(_coordinate_pairs(child, feature_id))
    return result


def _validate_geometry(geometry: object, feature_id: str) -> dict[str, Any]:
    value = _mapping(geometry, f"{feature_id} geometry")
    if value.get("type") not in {"Polygon", "MultiPolygon"}:
        raise ValueError(f"{feature_id}: geometry must be Polygon or MultiPolygon")
    for lon, lat in _coordinate_pairs(value.get("coordinates"), feature_id):
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise ValueError(f"{feature_id}: geometry must use WGS84 coordinates")
    return value


def _feature_hash(properties: dict[str, Any], geometry: dict[str, Any]) -> str:
    semantic_properties = {
        field: value
        for field, value in properties.items()
        if field not in CONSUMPTION_RUN_FIELDS
    }
    payload = json.dumps(
        {"properties": semantic_properties, "geometry": geometry},
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_consumption_records(
    collection: object,
    *,
    expected_release_commit: str,
    expected_container_image: str,
    expected_model_version: str,
    expected_metadata_contract_version: str,
    expected_quality_rule_version: str,
) -> list[ConsumptionRecord]:
    document = _mapping(collection, "Consumption output")
    if document.get("type") != "FeatureCollection":
        raise ValueError("Consumption output must be a GeoJSON FeatureCollection")
    features = document.get("features")
    if not isinstance(features, list) or not features:
        raise ValueError("Consumption output must contain features")

    records: list[ConsumptionRecord] = []
    seen: set[str] = set()
    for raw_feature in features:
        feature = _mapping(raw_feature, "Consumption feature")
        properties = _mapping(feature.get("properties"), "Consumption feature properties")
        feature_id = _string(properties, "feature_id", "Consumption feature")
        if feature.get("id") != feature_id:
            raise ValueError(f"{feature_id}: GeoJSON id must equal feature_id")
        if feature_id in seen:
            raise ValueError(f"Duplicate consumption feature_id: {feature_id}")
        seen.add(feature_id)

        normalized = {field: properties.get(field) for field in CONSUMPTION_FIELDS}
        for field in (
            "feature_uri",
            "spatial_unit_type",
            "spatial_unit_code",
            "name",
            "annual_value_status",
            "residential_value_status",
            "business_value_status",
            "allocation_method",
            "source_reference_period",
            "source_modified_at_status",
            "source_retrieved_at_status",
            "source_retrieved_on",
        ):
            normalized[field] = _string(properties, field, feature_id)
        normalized["annual_electricity_consumption_kwh"] = _nonnegative_number(
            properties, "annual_electricity_consumption_kwh", feature_id
        )
        normalized["annual_electricity_kwh"] = _nonnegative_number(
            properties, "annual_electricity_kwh", feature_id
        )
        if (
            normalized["annual_electricity_consumption_kwh"]
            != normalized["annual_electricity_kwh"]
        ):
            raise ValueError(f"{feature_id}: annual electricity compatibility fields drift")
        for field in (
            "residential_electricity_kwh",
            "business_electricity_kwh",
            "services_commerce_electricity_kwh",
            "unknown_industrial_business_electricity_kwh",
            "unknown_business_electricity_kwh",
        ):
            normalized[field] = _nonnegative_number(
                properties, field, feature_id, nullable=True
            )
        for field in ("source_ids", "sources", "quality_flags"):
            if not isinstance(properties.get(field), list):
                raise TypeError(f"{feature_id}: {field} must be an array")

        quality = _mapping(properties.get("datacompleetheid"), f"{feature_id} datacompleetheid")
        score = quality.get("score")
        if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 3:
            raise ValueError(f"{feature_id}: datacompleetheid score must be 0 through 3")
        if quality.get("rule_version") != expected_quality_rule_version:
            raise ValueError(f"{feature_id}: datacompleetheid rule version drift")
        normalized.update(
            {
                "datacompleetheid": score,
                "datacompleetheid_label": _string(quality, "label", feature_id),
                "datacompleetheid_rule_version": expected_quality_rule_version,
                "datacompleetheid_assessed_at": _timestamp(
                    quality.get("assessed_at"), "datacompleetheid.assessed_at", feature_id
                ),
                "datacompleetheid_evidence": _mapping(
                    quality.get("evidence"), f"{feature_id} datacompleetheid evidence"
                ),
                "datacompleetheid_reason_codes": quality.get("reason_codes"),
                "datacompleetheid_explanation": _string(quality, "explanation", feature_id),
            }
        )
        if not isinstance(normalized["datacompleetheid_reason_codes"], list):
            raise TypeError(f"{feature_id}: datacompleetheid reason_codes must be an array")

        normalized["source_modified_at"] = _timestamp(
            properties.get("source_modified_at"), "source_modified_at", feature_id, nullable=True
        )
        normalized["source_retrieved_at"] = _timestamp(
            properties.get("source_retrieved_at"), "source_retrieved_at", feature_id, nullable=True
        )
        normalized["model_run_at"] = _timestamp(
            properties.get("model_run_at"), "model_run_at", feature_id
        )
        normalized["output_generated_at"] = _timestamp(
            properties.get("output_generated_at"), "output_generated_at", feature_id
        )
        for field, expected in (
            ("model_version", expected_model_version),
            ("metadata_contract_version", expected_metadata_contract_version),
            ("release_commit", expected_release_commit),
            ("container_image", expected_container_image),
        ):
            if properties.get(field) != expected:
                raise ValueError(f"{feature_id}: {field} drift")
            normalized[field] = expected
        normalized["provenance"] = _mapping(properties.get("provenance"), f"{feature_id} provenance")
        geometry = _validate_geometry(feature.get("geometry"), feature_id)
        records.append(
            ConsumptionRecord(
                properties=normalized,
                geometry_json=json.dumps(geometry, separators=(",", ":")),
                source_feature_hash=_feature_hash(normalized, geometry),
            )
        )
    return records


def _request(session: Any, method: str, url: str, *, timeout: int, **kwargs: Any) -> Any:
    return session.request(method, url, timeout=timeout, **kwargs)


def _json_response(response: Any, step: str) -> dict[str, Any]:
    response.raise_for_status()
    try:
        return _mapping(response.json(), step)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{step} did not return a JSON object") from exc


def _same_origin_url(base_url: str, path: str) -> str:
    target = urljoin(f"{base_url.rstrip('/')}/", path.lstrip("/"))
    base = urlparse(base_url)
    parsed = urlparse(target)
    if parsed.scheme != base.scheme or parsed.netloc != base.netloc:
        raise ValueError("Consumption output data link must remain on the configured API origin")
    return target


def fetch_consumption_artifact(
    base_url: str,
    *,
    expected_release_commit: str,
    expected_container_image: str,
    expected_model_version: str,
    expected_metadata_contract_version: str,
    expected_quality_rule_version: str,
    session: Any = requests,
    timeout: int = 300,
) -> ConsumptionArtifact:
    base_url = base_url.rstrip("/")
    ready = _json_response(
        _request(session, "GET", f"{base_url}/readyz", timeout=30), "GET /readyz"
    )
    if ready.get("status") != "ready" or ready.get("reasons") != []:
        raise RuntimeError("Consumption API is not ready")
    for field, expected in (
        ("release_commit", expected_release_commit),
        ("container_image", expected_container_image),
    ):
        if ready.get(field) != expected:
            raise ValueError(f"GET /readyz: {field} drift")
    runtime_state = _mapping(ready.get("runtime_state"), "GET /readyz runtime_state")
    state_fingerprint = _string(runtime_state, "state_fingerprint", "GET /readyz")

    metadata = _json_response(
        _request(session, "GET", f"{base_url}/metadata", timeout=30), "GET /metadata"
    )
    for field, expected in (
        ("model_id", "consumption-map"),
        ("model_version", expected_model_version),
        ("metadata_contract_version", expected_metadata_contract_version),
        ("release_commit", expected_release_commit),
        ("container_image", expected_container_image),
    ):
        if metadata.get(field) != expected:
            raise ValueError(f"GET /metadata: {field} drift")
    if metadata.get("ready") is not True:
        raise RuntimeError("Consumption metadata is not ready")

    layers = _json_response(
        _request(session, "GET", f"{base_url}/layers", timeout=30), "GET /layers"
    )
    layer_records = layers.get("layers")
    if not isinstance(layer_records, list):
        raise TypeError("GET /layers: layers must be an array")
    layer = next(
        (item for item in layer_records if isinstance(item, dict) and item.get("layer_id") == CONSUMPTION_LAYER_ID),
        None,
    )
    if layer is None or layer.get("media_type") != CONSUMPTION_MEDIA_TYPE:
        raise ValueError("GET /layers: consumption layer contract drift")

    request_body = {
        "dataset_id": "alkmaar_2023",
        "layer_ids": [CONSUMPTION_LAYER_ID],
        "selection": {"municipality_code": "GM0361"},
    }
    run = _json_response(
        _request(session, "POST", f"{base_url}/v1/runs", timeout=timeout, json=request_body),
        "POST /v1/runs",
    )
    run_id = _string(run, "run_id", "POST /v1/runs")
    deadline = time.monotonic() + timeout
    while True:
        stored_run = _json_response(
            _request(
                session,
                "GET",
                f"{base_url}/v1/runs/{run_id}",
                timeout=30,
            ),
            "GET /v1/runs/{run_id}",
        )
        status = stored_run.get("status")
        if status == "succeeded":
            break
        if status == "failed":
            raise RuntimeError("Consumption run failed")
        if time.monotonic() >= deadline:
            raise RuntimeError("Consumption run did not complete in time")
        time.sleep(0.25)
    for field, expected in (
        ("release_commit", expected_release_commit),
        ("container_image", expected_container_image),
    ):
        if stored_run.get(field) != expected:
            raise ValueError(f"GET run: {field} drift")
    output_ids = stored_run.get("output_ids")
    if not isinstance(output_ids, list) or len(output_ids) != 1:
        raise ValueError("Completed Consumption run must return exactly one output ID")
    output_id = output_ids[0]
    if not isinstance(output_id, str) or not output_id:
        raise ValueError("Completed Consumption run returned an invalid output ID")

    output = _json_response(
        _request(
            session,
            "GET",
            f"{base_url}/v1/outputs/{output_id}",
            timeout=30,
        ),
        "GET /v1/outputs/{output_id}",
    )
    if (
        output.get("status") != "available"
        or output.get("layer_id") != CONSUMPTION_LAYER_ID
        or output.get("media_type") != CONSUMPTION_MEDIA_TYPE
    ):
        raise ValueError("GET output: consumption output contract drift")
    data_url = _same_origin_url(base_url, _string(output, "data_url", "GET output"))
    data_response = _request(session, "GET", data_url, timeout=timeout)
    data_response.raise_for_status()
    if data_response.headers.get("content-type", "").split(";", 1)[0] != CONSUMPTION_MEDIA_TYPE:
        raise ValueError("Consumption output response media type drift")
    try:
        collection = json.loads(data_response.content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Consumption output is not valid UTF-8 GeoJSON") from exc
    semantic_hash = hashlib.sha256(data_response.content).hexdigest()
    if semantic_hash != output.get("semantic_sha256"):
        raise ValueError("Consumption output semantic SHA-256 mismatch")
    records = load_consumption_records(
        collection,
        expected_release_commit=expected_release_commit,
        expected_container_image=expected_container_image,
        expected_model_version=expected_model_version,
        expected_metadata_contract_version=expected_metadata_contract_version,
        expected_quality_rule_version=expected_quality_rule_version,
    )
    if len(records) != output.get("feature_count"):
        raise ValueError("Consumption output feature count mismatch")
    return ConsumptionArtifact(
        records=records,
        release_commit=expected_release_commit,
        container_image=expected_container_image,
        output_id=output_id,
        output_generated_at=_string(output, "output_generated_at", "GET output"),
        state_fingerprint=state_fingerprint,
    )


def get_consumption_readiness_signature(base_url: str, *, session: Any = requests) -> tuple[str, str]:
    ready = _json_response(
        _request(session, "GET", f"{base_url.rstrip('/')}/readyz", timeout=30),
        "GET /readyz",
    )
    if ready.get("status") != "ready" or ready.get("reasons") != []:
        raise RuntimeError("Consumption API is not ready")
    state = _mapping(ready.get("runtime_state"), "GET /readyz runtime_state")
    return (
        _string(state, "state_fingerprint", "GET /ready"),
        _string(state, "initialized_at", "GET /ready"),
    )
