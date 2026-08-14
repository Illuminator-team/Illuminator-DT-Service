import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urljoin, urlparse

import requests


EV_LAYER_ID = "public_ev_chargers"
EV_MEDIA_TYPE = "application/geo+json"
EV_FIELDS = (
    "feature_id",
    "feature_uri",
    "source_feature_id",
    "address",
    "operator_name",
    "cpo_id",
    "reported_open",
    "connector_count",
    "available_connector_count",
    "max_power_kw",
    "connector_types",
    "power_types",
    "source_feature_modified_at",
    "linked_connector_count",
    "unsupported_connector_count",
    "modeled_annual_energy_kwh",
    "modeled_annual_peak_kw",
    "profile_available",
    "profile_summary_kind",
    "datacompleetheid",
    "datacompleetheid_label",
    "datacompleetheid_method_version",
    "datacompleetheid_assessed_at",
    "datacompleetheid_evidence",
    "completeness_reason",
    "model_id",
    "model_version",
    "metadata_contract_version",
    "release_commit",
    "container_image",
    "model_run_at",
    "output_generated_at",
    "source_retrieved_at",
    "output_id",
)
EV_RUN_FIELDS = {
    "model_run_at",
    "output_generated_at",
    "output_id",
    "datacompleetheid_assessed_at",
}


@dataclass(frozen=True)
class EvRecord:
    properties: dict[str, Any]
    geometry_json: str
    source_feature_hash: str


@dataclass(frozen=True)
class EvArtifact:
    records: list[EvRecord]
    release_commit: str
    container_image: str
    output_id: str
    output_generated_at: str
    runtime_artifact_sha256: str


def _mapping(value: object, step: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{step} must be an object")
    return value


def _string(mapping: dict[str, Any], field: str, step: str, *, nullable: bool = False) -> str | None:
    value = mapping.get(field)
    if value is None and nullable:
        return None
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


def _number(
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


def _feature_hash(properties: dict[str, Any], geometry: dict[str, Any]) -> str:
    semantic_properties = {
        field: value for field, value in properties.items() if field not in EV_RUN_FIELDS
    }
    payload = json.dumps(
        {"properties": semantic_properties, "geometry": geometry},
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_ev_records(
    collection: object,
    *,
    expected_release_commit: str,
    expected_container_image: str,
    expected_model_version: str,
    expected_metadata_contract_version: str,
    expected_quality_method_version: str,
) -> list[EvRecord]:
    document = _mapping(collection, "EV output")
    if document.get("type") != "FeatureCollection":
        raise ValueError("EV output must be a GeoJSON FeatureCollection")
    metadata = _mapping(document.get("metadata"), "EV output metadata")
    for field, expected in (
        ("model_id", "ev-map"),
        ("model_version", expected_model_version),
        ("metadata_contract_version", expected_metadata_contract_version),
        ("release_commit", expected_release_commit),
        ("container_image", expected_container_image),
        ("layer_id", EV_LAYER_ID),
    ):
        if metadata.get(field) != expected:
            raise ValueError(f"EV output metadata: {field} drift")
    features = document.get("features")
    if not isinstance(features, list) or not features:
        raise ValueError("EV output must contain features")

    records: list[EvRecord] = []
    seen: set[str] = set()
    for raw_feature in features:
        feature = _mapping(raw_feature, "EV feature")
        properties = _mapping(feature.get("properties"), "EV feature properties")
        feature_id = _string(properties, "feature_id", "EV feature")
        assert isinstance(feature_id, str)
        if feature.get("id") != feature_id:
            raise ValueError(f"{feature_id}: GeoJSON id must equal feature_id")
        if feature_id in seen:
            raise ValueError(f"Duplicate EV feature_id: {feature_id}")
        seen.add(feature_id)

        normalized = {field: properties.get(field) for field in EV_FIELDS}
        for field in ("feature_uri", "source_feature_id", "datacompleetheid_label", "completeness_reason", "model_id"):
            normalized[field] = _string(properties, field, feature_id)
        for field in ("address", "operator_name", "cpo_id", "profile_summary_kind"):
            normalized[field] = _string(properties, field, feature_id, nullable=True)
        for field in ("connector_count", "available_connector_count", "linked_connector_count", "unsupported_connector_count"):
            value = properties.get(field)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{feature_id}: {field} must be a non-negative integer")
            normalized[field] = value
        for field in ("max_power_kw", "modeled_annual_energy_kwh", "modeled_annual_peak_kw"):
            normalized[field] = _number(properties, field, feature_id, nullable=True)
        for field in ("connector_types", "power_types"):
            value = properties.get(field)
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise TypeError(f"{feature_id}: {field} must be a string array")
        for field in ("reported_open", "profile_available"):
            value = properties.get(field)
            if value is not None and not isinstance(value, bool):
                raise TypeError(f"{feature_id}: {field} must be boolean or null")
        score = properties.get("datacompleetheid")
        if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 3:
            raise ValueError(f"{feature_id}: datacompleetheid must be 0 through 3")
        if properties.get("datacompleetheid_method_version") != expected_quality_method_version:
            raise ValueError(f"{feature_id}: datacompleetheid method version drift")
        normalized["datacompleetheid_evidence"] = _mapping(
            properties.get("datacompleetheid_evidence"), f"{feature_id} datacompleetheid evidence"
        )
        for field in (
            "source_feature_modified_at",
            "datacompleetheid_assessed_at",
            "model_run_at",
            "output_generated_at",
            "source_retrieved_at",
        ):
            normalized[field] = _timestamp(
                properties.get(field), field, feature_id, nullable=field == "source_feature_modified_at"
            )
        for field, expected in (
            ("model_id", "ev-map"),
            ("model_version", expected_model_version),
            ("metadata_contract_version", expected_metadata_contract_version),
            ("release_commit", expected_release_commit),
            ("container_image", expected_container_image),
        ):
            if properties.get(field) != expected:
                raise ValueError(f"{feature_id}: {field} drift")
            normalized[field] = expected
        normalized["output_id"] = _string(properties, "output_id", feature_id)

        geometry = _mapping(feature.get("geometry"), f"{feature_id} geometry")
        coordinates = geometry.get("coordinates")
        if geometry.get("type") != "Point" or not isinstance(coordinates, list) or len(coordinates) < 2:
            raise ValueError(f"{feature_id}: geometry must be a Point")
        lon, lat = coordinates[:2]
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in (lon, lat)):
            raise TypeError(f"{feature_id}: Point coordinates must be numeric")
        if not (-180 <= float(lon) <= 180 and -90 <= float(lat) <= 90):
            raise ValueError(f"{feature_id}: geometry must use WGS84 coordinates")
        records.append(
            EvRecord(
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
        raise ValueError("EV output data link must remain on the configured API origin")
    return target


def _identity(document: dict[str, Any], *, release_commit: str, container_image: str, step: str) -> None:
    if document.get("release_commit") != release_commit:
        raise ValueError(f"{step}: release_commit drift")
    if document.get("container_image") != container_image:
        raise ValueError(f"{step}: container_image drift")


def fetch_ev_artifact(
    base_url: str,
    *,
    expected_release_commit: str,
    expected_container_image: str,
    expected_model_version: str,
    expected_metadata_contract_version: str,
    expected_quality_method_version: str,
    session: Any = requests,
    timeout: int = 300,
) -> EvArtifact:
    base_url = base_url.rstrip("/")
    ready = _json_response(
        _request(session, "GET", f"{base_url}/ready", timeout=30), "GET /ready"
    )
    if ready.get("ready") is not True or ready.get("state") != "ready":
        raise RuntimeError("EV API is not ready")
    _identity(
        ready,
        release_commit=expected_release_commit,
        container_image=expected_container_image,
        step="GET /ready",
    )
    if ready.get("model_version") != expected_model_version:
        raise ValueError("GET /ready: model version drift")
    runtime_hash = _string(ready, "runtime_artifact_sha256", "GET /ready")
    assert isinstance(runtime_hash, str)

    metadata = _json_response(
        _request(session, "GET", f"{base_url}/metadata", timeout=30), "GET /metadata"
    )
    runtime = _mapping(metadata.get("runtime"), "GET /metadata runtime")
    _identity(
        runtime,
        release_commit=expected_release_commit,
        container_image=expected_container_image,
        step="GET /metadata",
    )
    model = _mapping(metadata.get("model"), "GET /metadata model")
    if model.get("id") != "ev-map" or model.get("version") != expected_model_version:
        raise ValueError("GET /metadata: model identity drift")
    if metadata.get("metadata_contract_version") != expected_metadata_contract_version:
        raise ValueError("GET /metadata: metadata contract version drift")

    layers = _json_response(
        _request(session, "GET", f"{base_url}/layers", timeout=30), "GET /layers"
    )
    _identity(
        layers,
        release_commit=expected_release_commit,
        container_image=expected_container_image,
        step="GET /layers",
    )
    layer_records = layers.get("layers")
    if not isinstance(layer_records, list):
        raise TypeError("GET /layers: layers must be an array")
    layer = next(
        (item for item in layer_records if isinstance(item, dict) and item.get("id") == EV_LAYER_ID),
        None,
    )
    if layer is None or layer.get("geometry_type") != "Point":
        raise ValueError("GET /layers: EV charger layer contract drift")

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
    if run.get("status") != "succeeded":
        raise RuntimeError("EV run did not succeed")
    _identity(
        run,
        release_commit=expected_release_commit,
        container_image=expected_container_image,
        step="POST /runs",
    )
    run_links = _mapping(run.get("links"), "POST /runs links")
    stored_run_url = _same_origin_url(base_url, _string(run_links, "self", "POST /runs links"))
    stored_run = _json_response(
        _request(session, "GET", stored_run_url, timeout=30), "GET run"
    )
    if stored_run != run:
        raise ValueError("GET run does not match the completed EV run")
    output_links = run_links.get("outputs")
    if not isinstance(output_links, list) or len(output_links) != 1 or not isinstance(output_links[0], str):
        raise ValueError("EV run must expose exactly one output link")
    output = _json_response(
        _request(session, "GET", _same_origin_url(base_url, output_links[0]), timeout=30),
        "GET output",
    )
    _identity(
        output,
        release_commit=expected_release_commit,
        container_image=expected_container_image,
        step="GET output",
    )
    if (
        output.get("status") != "available"
        or output.get("layer_id") != EV_LAYER_ID
        or output.get("media_type") != EV_MEDIA_TYPE
        or output.get("model_version") != expected_model_version
        or output.get("metadata_contract_version") != expected_metadata_contract_version
        or output.get("datacompleetheid_method_version") != expected_quality_method_version
    ):
        raise ValueError("GET output: EV output contract drift")
    output_id = _string(output, "output_id", "GET output")
    assert isinstance(output_id, str)
    links = _mapping(output.get("links"), "GET output links")
    data_response = _request(
        session,
        "GET",
        _same_origin_url(base_url, _string(links, "data", "GET output links")),
        timeout=timeout,
    )
    data_response.raise_for_status()
    content = data_response.content
    if len(content) != output.get("byte_size") or hashlib.sha256(content).hexdigest() != output.get("sha256"):
        raise ValueError("EV output byte integrity mismatch")
    if data_response.headers.get("content-type", "").split(";", 1)[0] != EV_MEDIA_TYPE:
        raise ValueError("EV output response media type drift")
    try:
        collection = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("EV output is not valid UTF-8 GeoJSON") from exc
    records = load_ev_records(
        collection,
        expected_release_commit=expected_release_commit,
        expected_container_image=expected_container_image,
        expected_model_version=expected_model_version,
        expected_metadata_contract_version=expected_metadata_contract_version,
        expected_quality_method_version=expected_quality_method_version,
    )
    if len(records) != output.get("feature_count"):
        raise ValueError("EV output feature count mismatch")
    return EvArtifact(
        records=records,
        release_commit=expected_release_commit,
        container_image=expected_container_image,
        output_id=output_id,
        output_generated_at=_string(output, "output_generated_at", "GET output"),
        runtime_artifact_sha256=runtime_hash,
    )


def get_ev_readiness_signature(base_url: str, *, session: Any = requests) -> tuple[str, str]:
    ready = _json_response(
        _request(session, "GET", f"{base_url.rstrip('/')}/ready", timeout=30), "GET /ready"
    )
    if ready.get("ready") is not True or ready.get("state") != "ready":
        raise RuntimeError("EV API is not ready")
    return (
        _string(ready, "runtime_artifact_sha256", "GET /ready"),
        _string(ready, "profile_runtime_artifact_sha256", "GET /ready"),
    )
