import copy
import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import quote, urljoin, urlparse
from uuid import UUID

import requests

HEAT_MODEL_ID = "https://reformers01.ewi.tudelft.nl/id/model/heat-net-map"
HEAT_PERSISTENT_BASE = "https://reformers01.ewi.tudelft.nl/id/heat-net-map"
HEAT_MEDIA_TYPE = "application/geo+json"
HEAT_CRS_DESCRIPTION = "OGC:CRS84; longitude, latitude; RFC 7946"
HEAT_QUALITY_METHOD = "datacompleetheid-heat-net-v1"
HEAT_METHOD_ID = "alkmaar-heat-network-evidence-v1"
HEAT_STABLE_FIXTURE = "pc6-1812ab"
PC6_PATTERN = re.compile(r"^[0-9]{4}[A-Z]{2}$")

HEAT_COMMON_FIELDS = (
    "feature_id",
    "persistent_uri",
    "layer_id",
    "evidence_status",
    "datacompleetheid",
    "datacompleetheid_label",
    "datacompleetheid_rule_version",
    "fixture_only",
    "quality_evidence",
    "provenance",
    "all_properties",
)

HEAT_LAYER_DEFINITIONS = {
    "reported_neighbourhood_heat_consumers": {
        "geometry": "multipolygon",
        "allowed_geometry": {"Polygon", "MultiPolygon"},
        "canonical_fields": (
            "consumer_area_id",
            "area_name",
            "reference_year",
            "reported_connected_share_pct",
            "connected_dwellings_estimate",
            "heat_demand_estimate_gj_per_year",
            "heat_demand_low_gj_per_year",
            "heat_demand_high_gj_per_year",
        ),
        "identifiers": {"consumer_area_id"},
        "strings": {"area_name"},
        "integers": {"reference_year", "connected_dwellings_estimate"},
        "numbers": {
            "reported_connected_share_pct",
            "heat_demand_estimate_gj_per_year",
            "heat_demand_low_gj_per_year",
            "heat_demand_high_gj_per_year",
        },
        "nullable": set(),
    },
    "inferred_pc6_heat_consumers": {
        "geometry": "multipolygon",
        "allowed_geometry": {"Polygon", "MultiPolygon"},
        "canonical_fields": (
            "postcode6",
            "allocated_connected_dwellings_est",
            "heat_demand_gj_year_est",
            "gas_avg_m3",
            "electricity_avg_kwh",
            "inference_class",
            "corroboration",
            "liander_crosscheck_status",
        ),
        "identifiers": set(),
        "strings": {
            "postcode6",
            "inference_class",
            "corroboration",
            "liander_crosscheck_status",
        },
        "integers": {"allocated_connected_dwellings_est"},
        "numbers": {
            "heat_demand_gj_year_est",
            "gas_avg_m3",
            "electricity_avg_kwh",
        },
        "nullable": {"gas_avg_m3", "electricity_avg_kwh"},
    },
    "registered_heat_network_developments": {
        "geometry": "multipolygon",
        "allowed_geometry": {"Polygon", "MultiPolygon"},
        "canonical_fields": (
            "development_area_id",
            "development_name",
            "development_phase",
            "status_date",
            "planned_consumer_scale",
            "planned_heat_source_description",
        ),
        "identifiers": {"development_area_id"},
        "strings": {
            "development_name",
            "development_phase",
            "planned_consumer_scale",
            "planned_heat_source_description",
        },
        "integers": set(),
        "numbers": set(),
        "timestamps": {"status_date"},
        "nullable": {"status_date"},
    },
    "documented_actual_heat_sources": {
        "geometry": "point",
        "allowed_geometry": {"Point"},
        "canonical_fields": ("source_name", "source_status", "technology"),
        "identifiers": set(),
        "strings": {"source_name", "source_status", "technology"},
        "integers": set(),
        "numbers": set(),
        "nullable": set(),
    },
    "documented_large_heat_consumers": {
        "geometry": "point",
        "allowed_geometry": {"Point"},
        "canonical_fields": (
            "consumer_name",
            "connection_evidence",
            "annual_heat_consumption",
        ),
        "identifiers": set(),
        "strings": {"consumer_name", "connection_evidence"},
        "integers": set(),
        "numbers": {"annual_heat_consumption"},
        "nullable": {"annual_heat_consumption"},
    },
    "potential_heat_sources": {
        "geometry": "point",
        "allowed_geometry": {"Point"},
        "canonical_fields": (
            "source_name",
            "source_type",
            "potential_thermal_capacity_mw",
            "temperature_c",
            "candidate_status",
        ),
        "identifiers": set(),
        "strings": {"source_name", "source_type", "candidate_status"},
        "integers": set(),
        "numbers": {"potential_thermal_capacity_mw", "temperature_c"},
        "nullable": {
            "potential_thermal_capacity_mw",
            "temperature_c",
            "candidate_status",
        },
    },
}

HEAT_LAYER_IDS = tuple(HEAT_LAYER_DEFINITIONS)
HEAT_VOLATILE_PROVENANCE_FIELDS = {
    "api_run_id",
    "api_output_id",
    "api_run_at",
    "output_generated_at",
}


@dataclass(frozen=True)
class HeatRecord:
    layer_id: str
    properties: dict[str, Any]
    canonical: dict[str, Any]
    source_feature_hash: str
    geometry_json: str

    @property
    def feature_id(self) -> str:
        return self.properties["feature_id"]


@dataclass(frozen=True)
class HeatLayerArtifact:
    layer_id: str
    records: list[HeatRecord]
    output_id: str
    generated_at: str


@dataclass(frozen=True)
class HeatArtifact:
    layers: dict[str, HeatLayerArtifact]
    run_id: str
    release_commit: str
    container_digest: str
    snapshot_id: str
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


def _uuid(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a UUID string")
    try:
        UUID(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be a UUID string") from exc
    return value


def _timestamp(value: object, field: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include a timezone")
    return value


def _number(
    value: object,
    field: str,
    *,
    nullable: bool,
    nonnegative: bool = True,
) -> float | None:
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized) or (nonnegative and normalized < 0):
        qualifier = "finite and non-negative" if nonnegative else "finite"
        raise ValueError(f"{field} must be {qualifier}")
    return normalized


def _integer(value: object, field: str, *, nullable: bool) -> int | None:
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be an integer")
    if value < 0:
        raise ValueError(f"{field} must be non-negative")
    return value


def _positions(value: object):
    if (
        isinstance(value, list)
        and len(value) >= 2
        and all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in value[:2])
    ):
        yield float(value[0]), float(value[1])
        return
    if isinstance(value, list):
        for child in value:
            yield from _positions(child)


def _validate_geometry(value: object, layer_id: str, feature_id: str) -> dict[str, Any]:
    geometry = _mapping(value, f"{feature_id}.geometry")
    if set(geometry) != {"type", "coordinates"}:
        raise ValueError(f"{feature_id}: geometry contract drift")
    if geometry.get("type") not in HEAT_LAYER_DEFINITIONS[layer_id]["allowed_geometry"]:
        raise ValueError(f"{feature_id}: geometry type drift")
    positions = list(_positions(geometry.get("coordinates")))
    if not positions:
        raise ValueError(f"{feature_id}: geometry has no positions")
    for longitude, latitude in positions:
        if not math.isfinite(longitude) or not math.isfinite(latitude):
            raise ValueError(f"{feature_id}: geometry coordinates must be finite")
        if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
            raise ValueError(f"{feature_id}: geometry is not WGS84")
    return geometry


def _canonical_properties(layer_id: str, properties: dict[str, Any]) -> dict[str, Any]:
    definition = HEAT_LAYER_DEFINITIONS[layer_id]
    missing = set(definition["canonical_fields"]) - set(properties)
    if missing:
        raise ValueError(f"{layer_id}: canonical field drift: missing={sorted(missing)}")
    canonical: dict[str, Any] = {}
    nullable = definition["nullable"]
    for field in definition["canonical_fields"]:
        value = properties[field]
        if field in definition["identifiers"]:
            if value is None:
                raise ValueError(f"{layer_id}.{field} must be present")
            value = str(value)
        elif field in definition["strings"]:
            if value is None and field in nullable:
                pass
            elif not isinstance(value, str) or not value:
                raise ValueError(f"{layer_id}.{field} must be a non-empty string")
        elif field in definition["integers"]:
            value = _integer(value, f"{layer_id}.{field}", nullable=field in nullable)
        elif field in definition["numbers"]:
            value = _number(
                value,
                f"{layer_id}.{field}",
                nullable=field in nullable,
                nonnegative=field != "temperature_c",
            )
        elif field in definition.get("timestamps", set()):
            value = _timestamp(value, f"{layer_id}.{field}", nullable=field in nullable)
        canonical[field] = value
    if layer_id == "reported_neighbourhood_heat_consumers":
        if canonical["reported_connected_share_pct"] > 100:
            raise ValueError("reported connected share must be from 0 to 100")
    if layer_id == "inferred_pc6_heat_consumers":
        if not PC6_PATTERN.fullmatch(canonical["postcode6"]):
            raise ValueError("Heat PC6 identifier drift")
    return canonical


def _stable_feature_hash(properties: dict[str, Any], geometry: dict[str, Any]) -> str:
    stable_properties = copy.deepcopy(properties)
    provenance = stable_properties.get("provenance")
    if isinstance(provenance, dict):
        for field in HEAT_VOLATILE_PROVENANCE_FIELDS:
            provenance.pop(field, None)
    encoded = json.dumps(
        {"properties": stable_properties, "geometry": geometry},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def load_heat_layer_records(
    collection: object,
    *,
    layer_id: str,
    expected_run_id: str,
    expected_output_id: str,
    expected_model_version: str,
    expected_data_mode: str,
) -> list[HeatRecord]:
    if layer_id not in HEAT_LAYER_DEFINITIONS:
        raise ValueError(f"Unsupported Heat layer: {layer_id}")
    document = _mapping(collection, f"Heat {layer_id} GeoJSON")
    expected_document_fields = {
        "type",
        "features",
        "layer_id",
        "crs_description",
        "run_id",
        "output_id",
        "generated_at",
    }
    if set(document) != expected_document_fields:
        raise ValueError(f"{layer_id}: FeatureCollection contract drift")
    if document.get("type") != "FeatureCollection" or document.get("layer_id") != layer_id:
        raise ValueError(f"{layer_id}: FeatureCollection identity drift")
    if document.get("crs_description") != HEAT_CRS_DESCRIPTION:
        raise ValueError(f"{layer_id}: CRS drift")
    if _uuid(document.get("run_id"), f"{layer_id}.run_id") != expected_run_id:
        raise ValueError(f"{layer_id}: run ID drift")
    if _uuid(document.get("output_id"), f"{layer_id}.output_id") != expected_output_id:
        raise ValueError(f"{layer_id}: output ID drift")
    _timestamp(document.get("generated_at"), f"{layer_id}.generated_at")
    features = document.get("features")
    if not isinstance(features, list):
        raise TypeError(f"{layer_id}: features must be an array")

    records: list[HeatRecord] = []
    feature_ids: set[str] = set()
    for feature in features:
        item = _mapping(feature, f"{layer_id} feature")
        if set(item) != {"type", "id", "geometry", "properties"}:
            raise ValueError(f"{layer_id}: feature contract drift")
        if item.get("type") != "Feature":
            raise ValueError(f"{layer_id}: feature type drift")
        feature_id = item.get("id")
        if not isinstance(feature_id, str) or not feature_id or len(feature_id) > 200:
            raise ValueError(f"{layer_id}: feature ID drift")
        if feature_id in feature_ids:
            raise ValueError(f"{layer_id}: duplicate feature ID {feature_id}")
        properties = copy.deepcopy(_mapping(item.get("properties"), f"{feature_id}.properties"))
        required = {
            "feature_id",
            "persistent_uri",
            "layer_id",
            "evidence_status",
            "datacompleetheid",
            "datacompleetheid_label",
            "datacompleetheid_rule_version",
            "quality_evidence",
            "provenance",
        }
        missing = required - set(properties)
        if missing:
            raise ValueError(f"{feature_id}: common property drift: missing={sorted(missing)}")
        if properties["feature_id"] != feature_id or properties["layer_id"] != layer_id:
            raise ValueError(f"{feature_id}: feature identity drift")
        expected_uri = f"{HEAT_PERSISTENT_BASE}/{quote(layer_id, safe='')}/{quote(feature_id, safe='')}"
        if properties["persistent_uri"] != expected_uri:
            raise ValueError(f"{feature_id}: persistent URI drift")
        if not isinstance(properties["evidence_status"], str) or not properties["evidence_status"]:
            raise ValueError(f"{feature_id}: evidence status drift")
        score = properties["datacompleetheid"]
        if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 3:
            raise ValueError(f"{feature_id}: datacompleetheid must be from 0 to 3")
        if not isinstance(properties["datacompleetheid_label"], str) or not properties["datacompleetheid_label"]:
            raise ValueError(f"{feature_id}: datacompleetheid label drift")
        if properties["datacompleetheid_rule_version"] != HEAT_QUALITY_METHOD:
            raise ValueError(f"{feature_id}: datacompleetheid method drift")

        quality = _mapping(properties["quality_evidence"], f"{feature_id}.quality_evidence")
        if set(quality) != {"reason_codes", "summary"}:
            raise ValueError(f"{feature_id}: quality evidence drift")
        if (
            not isinstance(quality["reason_codes"], list)
            or not quality["reason_codes"]
            or not all(isinstance(item, str) and item for item in quality["reason_codes"])
            or not isinstance(quality["summary"], str)
            or not quality["summary"]
        ):
            raise ValueError(f"{feature_id}: invalid quality evidence")

        provenance = _mapping(properties["provenance"], f"{feature_id}.provenance")
        provenance_required = {
            "model_id",
            "model_version",
            "method_id",
            "method_version",
            "scientific_model_run_at",
            "api_snapshot_published_at",
            "api_run_id",
            "api_output_id",
            "api_run_at",
            "output_generated_at",
            "sources",
        }
        if provenance_required - set(provenance):
            raise ValueError(f"{feature_id}: provenance contract drift")
        if provenance["model_id"] != HEAT_MODEL_ID:
            raise ValueError(f"{feature_id}: model ID drift")
        if provenance["model_version"] != expected_model_version:
            raise ValueError(f"{feature_id}: model version drift")
        if provenance["method_id"] != HEAT_METHOD_ID or provenance["method_version"] != "1.0.0":
            raise ValueError(f"{feature_id}: method identity drift")
        if _uuid(provenance["api_run_id"], f"{feature_id}.api_run_id") != expected_run_id:
            raise ValueError(f"{feature_id}: provenance run ID drift")
        if _uuid(provenance["api_output_id"], f"{feature_id}.api_output_id") != expected_output_id:
            raise ValueError(f"{feature_id}: provenance output ID drift")
        for field in (
            "api_snapshot_published_at",
            "api_run_at",
            "output_generated_at",
        ):
            _timestamp(provenance[field], f"{feature_id}.{field}")
        _timestamp(
            provenance["scientific_model_run_at"],
            f"{feature_id}.scientific_model_run_at",
            nullable=True,
        )
        sources = provenance["sources"]
        if not isinstance(sources, list) or not sources:
            raise ValueError(f"{feature_id}: provenance sources are missing")
        for source in sources:
            source_record = _mapping(source, f"{feature_id}.source")
            if source_record.get("data_mode") != expected_data_mode:
                raise ValueError(f"{feature_id}: source data mode drift")
            checksum = source_record.get("sha256")
            if not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum):
                raise ValueError(f"{feature_id}: source checksum drift")

        fixture_only = properties.get("fixture_only")
        if expected_data_mode == "fixture" and fixture_only is not True:
            raise ValueError(f"{feature_id}: fixture marker is missing")
        if expected_data_mode == "real_source" and fixture_only is True:
            raise ValueError(f"{feature_id}: fixture data cannot be published as real source")
        properties["fixture_only"] = fixture_only is True
        canonical = _canonical_properties(layer_id, properties)
        properties.update(canonical)
        geometry = _validate_geometry(item.get("geometry"), layer_id, feature_id)
        records.append(
            HeatRecord(
                layer_id=layer_id,
                properties=properties,
                canonical=canonical,
                source_feature_hash=_stable_feature_hash(properties, geometry),
                geometry_json=json.dumps(geometry, ensure_ascii=True, separators=(",", ":")),
            )
        )
        feature_ids.add(feature_id)
    return records


def _request(session: Any, method: str, url: str, *, timeout: int, **kwargs: Any) -> Any:
    try:
        response = session.request(method, url, timeout=timeout, **kwargs)
        response.raise_for_status()
        return response
    except requests.RequestException as exc:
        raise RuntimeError(f"Heat API request failed: {method} {urlparse(url).path}") from exc


def _json_response(response: Any, step: str) -> dict[str, Any]:
    try:
        return _mapping(response.json(), step)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{step} did not return a JSON object") from exc


def _same_origin_url(base_url: str, path: str) -> str:
    target = urljoin(f"{base_url.rstrip('/')}/", path.lstrip("/"))
    base = urlparse(base_url)
    parsed = urlparse(target)
    if parsed.scheme != base.scheme or parsed.netloc != base.netloc:
        raise ValueError("Heat output data link must remain on the configured API origin")
    return target


def get_heat_readiness_signature(
    base_url: str,
    *,
    expected_data_mode: str | None = None,
    session: Any = requests,
) -> tuple[str, str, str, str]:
    ready = _json_response(
        _request(session, "GET", f"{base_url.rstrip('/')}/ready", timeout=30),
        "GET /ready",
    )
    if ready.get("status") != "ready":
        raise RuntimeError("Heat API is not ready")
    data_mode = _string(ready, "data_mode", "GET /ready")
    if expected_data_mode and data_mode != expected_data_mode:
        raise ValueError("GET /ready: data mode drift")
    return (
        _uuid(ready.get("snapshot_id"), "GET /ready snapshot_id"),
        data_mode,
        _timestamp(ready.get("initialized_at"), "GET /ready initialized_at"),
        _string(ready, "model_version", "GET /ready"),
    )


def fetch_heat_artifact(
    base_url: str,
    *,
    expected_release_commit: str,
    expected_container_digest: str,
    expected_model_version: str,
    expected_contract_version: str,
    expected_schema_contract_version: str,
    expected_data_mode: str,
    session: Any = requests,
    timeout: int = 300,
) -> HeatArtifact:
    base_url = base_url.rstrip("/")
    signature = get_heat_readiness_signature(
        base_url,
        expected_data_mode=expected_data_mode,
        session=session,
    )
    if signature[3] != expected_model_version:
        raise ValueError("GET /ready: model version drift")

    metadata = _json_response(
        _request(session, "GET", f"{base_url}/metadata", timeout=30),
        "GET /metadata",
    )
    model = _mapping(metadata.get("model"), "GET /metadata model")
    if model.get("id") != HEAT_MODEL_ID or model.get("version") != expected_model_version:
        raise ValueError("GET /metadata: model identity drift")
    if model.get("git_commit") != expected_release_commit:
        raise ValueError("GET /metadata: release commit drift")
    if metadata.get("contract_version") != expected_contract_version:
        raise ValueError("GET /metadata: contract version drift")
    if metadata.get("schema_contract_version") != expected_schema_contract_version:
        raise ValueError("GET /metadata: schema contract version drift")
    if metadata.get("crs", {}).get("output") != "OGC:CRS84":
        raise ValueError("GET /metadata: CRS drift")
    runtime = _mapping(metadata.get("runtime"), "GET /metadata runtime")
    if runtime.get("snapshot_id") != signature[0] or runtime.get("data_mode") != expected_data_mode:
        raise ValueError("GET /metadata: runtime identity drift")

    catalog = _json_response(
        _request(session, "GET", f"{base_url}/layers", timeout=30),
        "GET /layers",
    )
    if catalog.get("contract_version") != expected_contract_version:
        raise ValueError("GET /layers: contract version drift")
    layer_documents = catalog.get("layers")
    if not isinstance(layer_documents, list):
        raise TypeError("GET /layers: layers must be an array")
    by_id = {
        item.get("id"): item
        for item in layer_documents
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    if set(by_id) != set(HEAT_LAYER_IDS):
        raise ValueError("GET /layers: layer catalog drift")
    for layer_id, definition in HEAT_LAYER_DEFINITIONS.items():
        layer = by_id[layer_id]
        if set(layer.get("geometry", [])) != definition["allowed_geometry"]:
            raise ValueError(f"GET /layers: {layer_id} geometry drift")
        layer_runtime = _mapping(layer.get("runtime"), f"GET /layers {layer_id} runtime")
        if (
            layer_runtime.get("snapshot_id") != signature[0]
            or layer_runtime.get("data_mode") != expected_data_mode
            or isinstance(layer_runtime.get("feature_count"), bool)
            or not isinstance(layer_runtime.get("feature_count"), int)
            or layer_runtime.get("feature_count") < 0
        ):
            raise ValueError(f"GET /layers: {layer_id} runtime drift")

    run = _json_response(
        _request(
            session,
            "POST",
            f"{base_url}/runs",
            timeout=timeout,
            json={"layer_ids": list(HEAT_LAYER_IDS), "selection": {"type": "all"}},
        ),
        "POST /runs",
    )
    if run.get("status") != "completed":
        raise RuntimeError("POST /runs did not complete")
    run_id = _uuid(run.get("run_id"), "POST /runs run_id")
    outputs = run.get("outputs")
    if not isinstance(outputs, list) or len(outputs) != len(HEAT_LAYER_IDS):
        raise ValueError("POST /runs must return all six Heat outputs")
    output_summaries = {
        item.get("layer_id"): item for item in outputs if isinstance(item, dict)
    }
    if set(output_summaries) != set(HEAT_LAYER_IDS):
        raise ValueError("POST /runs output layer drift")

    stored_run = _json_response(
        _request(session, "GET", f"{base_url}/runs/{run_id}", timeout=30),
        "GET run",
    )
    if stored_run != run:
        raise ValueError("GET run does not match the completed Heat run")

    layer_artifacts: dict[str, HeatLayerArtifact] = {}
    for layer_id in HEAT_LAYER_IDS:
        summary = _mapping(output_summaries[layer_id], f"POST /runs {layer_id} output")
        output_id = _uuid(summary.get("output_id"), f"{layer_id} output_id")
        output = _json_response(
            _request(session, "GET", f"{base_url}/outputs/{output_id}", timeout=30),
            f"GET {layer_id} output",
        )
        if output.get("run_id") != run_id or output.get("layer_id") != layer_id:
            raise ValueError(f"GET output: {layer_id} identity drift")
        if output.get("status") != "available" or output.get("media_type") != HEAT_MEDIA_TYPE:
            raise ValueError(f"GET output: {layer_id} availability drift")
        metadata_snapshot = _mapping(
            output.get("metadata_snapshot"), f"GET {layer_id} metadata snapshot"
        )
        if (
            metadata_snapshot.get("model_id") != HEAT_MODEL_ID
            or metadata_snapshot.get("model_version") != expected_model_version
            or metadata_snapshot.get("contract_version") != expected_contract_version
            or metadata_snapshot.get("snapshot_id") != signature[0]
            or metadata_snapshot.get("data_mode") != expected_data_mode
        ):
            raise ValueError(f"GET output: {layer_id} metadata snapshot drift")
        links = _mapping(output.get("links"), f"GET {layer_id} output links")
        data_url = _same_origin_url(base_url, _string(links, "data", f"GET {layer_id} links"))
        response = _request(session, "GET", data_url, timeout=timeout)
        content = response.content
        if len(content) != output.get("byte_size"):
            raise ValueError(f"{layer_id}: output byte size drift")
        if hashlib.sha256(content).hexdigest() != output.get("sha256"):
            raise ValueError(f"{layer_id}: output checksum drift")
        if not response.headers.get("content-type", "").startswith(HEAT_MEDIA_TYPE):
            raise ValueError(f"{layer_id}: output media type drift")
        try:
            collection = json.loads(content)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{layer_id}: output is not valid JSON") from exc
        records = load_heat_layer_records(
            collection,
            layer_id=layer_id,
            expected_run_id=run_id,
            expected_output_id=output_id,
            expected_model_version=expected_model_version,
            expected_data_mode=expected_data_mode,
        )
        if len(records) != output.get("feature_count") or len(records) != summary.get("feature_count"):
            raise ValueError(f"{layer_id}: output feature count drift")
        layer_artifacts[layer_id] = HeatLayerArtifact(
            layer_id=layer_id,
            records=records,
            output_id=output_id,
            generated_at=_timestamp(output.get("generated_at"), f"{layer_id}.generated_at"),
        )

    fixture_records = layer_artifacts["inferred_pc6_heat_consumers"].records
    fixture = next(
        (record for record in fixture_records if record.feature_id == HEAT_STABLE_FIXTURE),
        None,
    )
    if expected_data_mode == "fixture":
        if fixture is None:
            raise ValueError(f"Heat stable fixture {HEAT_STABLE_FIXTURE} is missing")
        if fixture.canonical["allocated_connected_dwellings_est"] != 18:
            raise ValueError("Heat stable fixture dwelling count drift")
        if fixture.canonical["heat_demand_gj_year_est"] != 414:
            raise ValueError("Heat stable fixture demand drift")
        if fixture.properties["datacompleetheid"] != 2:
            raise ValueError("Heat stable fixture quality drift")

    return HeatArtifact(
        layers=layer_artifacts,
        run_id=run_id,
        release_commit=expected_release_commit,
        container_digest=expected_container_digest,
        snapshot_id=signature[0],
        initialized_at=signature[2],
        data_mode=expected_data_mode,
    )
