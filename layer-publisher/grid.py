import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urljoin, urlparse

import requests


GRID_LAYER_IDS = (
    "grid_lines",
    "grid_transformers",
    "grid_lv_mv_transformer_reach",
    "grid_mv_hv_transformer_reach",
)
GRID_MEDIA_TYPE = "application/geo+json"
GRID_MODEL_ID = "https://reformers01.ewi.tudelft.nl/id/model/liander-grid-topology"
GRID_COMPONENT_URI_PREFIX = "https://reformers01.ewi.tudelft.nl/id/grid-component/"
GRID_QUALITY_RULE = "datacompleetheid-grid-v1"
GRID_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")

GRID_COMMON_FIELDS = (
    "feature_id",
    "component_id",
    "persistent_uri",
    "component_type",
    "voltage_level",
    "nominal_voltage",
    "nominal_voltage_unit",
    "model_id",
    "model_version",
    "method_version",
    "grid_data_version",
    "source_reference_period",
    "source_modified_at",
    "source_retrieved_at",
    "source_last_updated",
    "cache_generated_at",
    "datacompleetheid",
    "datacompleetheid_label",
    "datacompleetheid_rule_version",
    "datacompleetheid_assessed_at",
    "datacompleetheid_reason_codes",
    "datacompleetheid_summary",
    "run_id",
    "output_id",
    "model_run_at",
    "output_generated_at",
)

GRID_LINE_FIELDS = (
    *GRID_COMMON_FIELDS,
    "model_component_name",
    "length_km",
    "in_service",
    "evidence_status",
    "connected_transformer_ids",
    "serving_transformer_id",
    "connected_mv_hv_transformer_ids",
    "serving_mv_hv_transformer_id",
    "root_bus_ids",
    "source_station_objectids",
)

GRID_TRANSFORMER_FIELDS = (
    *GRID_COMMON_FIELDS,
    "model_component_name",
    "transformer_type",
    "primary_nominal_voltage_kv",
    "secondary_nominal_voltage_kv",
    "rated_power_kva",
    "in_service",
    "source_station_objectid",
    "source_station_name",
    "upstream_mapping_status",
    "upstream_mapping_method",
    "upstream_mv_hv_transformer_id",
    "upstream_root_bus_id",
    "upstream_source_station_objectid",
    "upstream_candidate_root_bus_ids",
    "upstream_candidate_mv_hv_transformer_ids",
    "upstream_topology_path_edge_ids",
)

GRID_REACH_FIELDS = (
    *GRID_COMMON_FIELDS,
    "transformer_type",
    "pc6_id",
    "reach_level",
    "reach_method",
    "share_scope",
    "dominant_transformer_id",
    "dominant_transformer_name",
    "dominant_transformer_share",
    "dominant_transformer_share_percent",
    "dominant_root_bus_id",
    "runner_up_transformer_id",
    "runner_up_transformer_name",
    "runner_up_transformer_share",
    "runner_up_transformer_share_percent",
    "runner_up_root_bus_id",
    "share_margin",
    "share_margin_percentage_points",
    "entity_count",
    "has_overlap",
    "is_ambiguous",
    "ambiguity_reason",
    "ranked_shares",
    "matched_lv_cable_length_m",
    "match_method",
    "fallback_used",
    "fallback_bus_id",
    "fallback_distance_m",
    "match_evidence",
    "pc6_source_id",
    "pc6_source_sha256",
    "evidence_status",
)

GRID_LAYER_FIELDS = {
    "grid_lines": GRID_LINE_FIELDS,
    "grid_transformers": GRID_TRANSFORMER_FIELDS,
    "grid_lv_mv_transformer_reach": GRID_REACH_FIELDS,
    "grid_mv_hv_transformer_reach": GRID_REACH_FIELDS,
}

GRID_RUN_PROVENANCE_FIELDS = frozenset(
    {
        "run_id",
        "output_id",
        "model_run_at",
        "output_generated_at",
    }
)


@dataclass(frozen=True)
class GridRecord:
    layer_id: str
    properties: dict[str, Any]
    source_feature_hash: str
    geometry_json: str

    @property
    def component_id(self) -> str:
        return self.properties["component_id"]


@dataclass(frozen=True)
class GridArtifact:
    records_by_layer: dict[str, list[GridRecord]]
    release_commit: str
    container_digest: str
    grid_data_version: str
    data_mode: str
    output_ids: dict[str, str]


def _mapping(value: object, step: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{step} must be an object")
    return value


def _string(mapping: dict[str, Any], field: str, step: str) -> str:
    value = mapping.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{step}.{field} must be a non-empty string")
    return value


def _nullable_string(value: object, field: str, feature_id: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"{feature_id}: {field} must be null or a non-empty string")
    return value


def _nullable_identifier(
    value: object,
    field: str,
    feature_id: str,
) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError(f"{feature_id}: {field} must be null or an identifier")
    identifier = str(value).strip()
    if not identifier:
        raise ValueError(f"{feature_id}: {field} must be null or an identifier")
    return identifier


def _boolean(value: object, field: str, feature_id: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{feature_id}: {field} must be boolean")
    return value


def _share(
    value: object,
    field: str,
    feature_id: str,
    *,
    percent: bool = False,
    nullable: bool = False,
) -> float | None:
    number = _number(value, field, feature_id, nullable=nullable)
    if number is not None and number > (100 if percent else 1):
        raise ValueError(f"{feature_id}: {field} is outside its allowed range")
    return number


def _number(
    value: object,
    field: str,
    feature_id: str,
    *,
    nullable: bool = False,
) -> float | None:
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{feature_id}: {field} must be numeric")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{feature_id}: {field} must be finite and non-negative")
    return number


def _timestamp(
    value: object,
    field: str,
    feature_id: str,
    *,
    nullable: bool = False,
) -> str | None:
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


def _coordinate_pairs(value: object, feature_id: str) -> list[tuple[float, float]]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{feature_id}: geometry coordinates must be non-empty")
    if len(value) >= 2 and all(isinstance(item, (int, float)) for item in value[:2]):
        longitude, latitude = float(value[0]), float(value[1])
        if not math.isfinite(longitude) or not math.isfinite(latitude):
            raise ValueError(f"{feature_id}: geometry coordinates must be finite")
        return [(longitude, latitude)]
    pairs: list[tuple[float, float]] = []
    for child in value:
        pairs.extend(_coordinate_pairs(child, feature_id))
    return pairs


def _validate_geometry(
    geometry: object,
    *,
    layer_id: str,
    feature_id: str,
) -> dict[str, Any]:
    document = _mapping(geometry, f"{feature_id}.geometry")
    allowed_by_layer = {
        "grid_lines": {"LineString", "MultiLineString"},
        "grid_transformers": {"Point"},
        "grid_lv_mv_transformer_reach": {"Polygon", "MultiPolygon"},
        "grid_mv_hv_transformer_reach": {"Polygon", "MultiPolygon"},
    }
    allowed = allowed_by_layer[layer_id]
    if document.get("type") not in allowed:
        raise ValueError(f"{feature_id}: unexpected geometry type for {layer_id}")
    for longitude, latitude in _coordinate_pairs(document.get("coordinates"), feature_id):
        if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
            raise ValueError(f"{feature_id}: geometry is not WGS84")
    return document


def _feature_hash(properties: dict[str, Any], geometry: dict[str, Any]) -> str:
    stable_properties = {
        key: value
        for key, value in properties.items()
        if key not in GRID_RUN_PROVENANCE_FIELDS
    }
    encoded = json.dumps(
        {"properties": stable_properties, "geometry": geometry},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_common_properties(
    properties: dict[str, Any],
    *,
    feature_id: str,
    expected_model_version: str,
    expected_method_version: str,
    expected_grid_data_version: str,
) -> dict[str, Any]:
    normalized = dict(properties)
    if properties.get("feature_id") != feature_id or properties.get("component_id") != feature_id:
        raise ValueError(f"{feature_id}: feature/component identity drift")
    if not GRID_ID_PATTERN.fullmatch(feature_id):
        raise ValueError(f"{feature_id}: unsupported component ID")
    expected_uri = GRID_COMPONENT_URI_PREFIX + feature_id
    if properties.get("persistent_uri") != expected_uri:
        raise ValueError(f"{feature_id}: persistent URI drift")
    if properties.get("model_id") != GRID_MODEL_ID:
        raise ValueError(f"{feature_id}: model identity drift")
    if properties.get("model_version") != expected_model_version:
        raise ValueError(f"{feature_id}: model version drift")
    if properties.get("method_version") != expected_method_version:
        raise ValueError(f"{feature_id}: method version drift")
    if properties.get("grid_data_version") != expected_grid_data_version:
        raise ValueError(f"{feature_id}: grid data version drift")
    if properties.get("nominal_voltage_unit") != "kV":
        raise ValueError(f"{feature_id}: nominal voltage unit drift")

    normalized["nominal_voltage"] = _number(
        properties.get("nominal_voltage"),
        "nominal_voltage",
        feature_id,
        nullable=True,
    )
    for field in (
        "source_reference_period",
        "datacompleetheid_label",
        "datacompleetheid_summary",
        "run_id",
        "output_id",
    ):
        normalized[field] = _nullable_string(
            properties.get(field), field, feature_id
        )
    for field in ("source_modified_at", "source_last_updated"):
        normalized[field] = _timestamp(
            properties.get(field), field, feature_id, nullable=True
        )
    for field in (
        "source_retrieved_at",
        "cache_generated_at",
        "datacompleetheid_assessed_at",
        "model_run_at",
        "output_generated_at",
    ):
        normalized[field] = _timestamp(properties.get(field), field, feature_id)

    score = properties.get("datacompleetheid")
    if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 3:
        raise ValueError(f"{feature_id}: datacompleetheid must be an integer from 0 to 3")
    if properties.get("datacompleetheid_rule_version") != GRID_QUALITY_RULE:
        raise ValueError(f"{feature_id}: datacompleetheid rule drift")
    reasons = properties.get("datacompleetheid_reason_codes")
    if not isinstance(reasons, list) or not reasons or not all(
        isinstance(item, str) and item for item in reasons
    ):
        raise ValueError(f"{feature_id}: invalid datacompleetheid reason codes")
    normalized["datacompleetheid_reason_codes"] = reasons
    return normalized


def load_grid_records(
    collection: object,
    *,
    layer_id: str,
    expected_model_version: str,
    expected_method_version: str,
    expected_grid_data_version: str,
    expected_output_id: str,
) -> list[GridRecord]:
    if layer_id not in GRID_LAYER_IDS:
        raise ValueError(f"Unsupported grid layer: {layer_id}")
    document = _mapping(collection, f"{layer_id} GeoJSON")
    if document.get("type") != "FeatureCollection":
        raise ValueError(f"{layer_id} output must be a GeoJSON FeatureCollection")
    features = document.get("features")
    if not isinstance(features, list) or not features:
        raise ValueError(f"{layer_id} output must contain features")

    records: list[GridRecord] = []
    component_ids: set[str] = set()
    expected_fields = GRID_LAYER_FIELDS[layer_id]
    for feature in features:
        feature_document = _mapping(feature, f"{layer_id} feature")
        properties = _mapping(
            feature_document.get("properties"), f"{layer_id} feature properties"
        )
        feature_id = _string(properties, "feature_id", f"{layer_id} feature")
        if feature_document.get("id") != feature_id:
            raise ValueError(f"{feature_id}: top-level feature ID drift")
        if feature_id in component_ids:
            raise ValueError(f"Duplicate grid component_id: {feature_id}")
        missing = [field for field in expected_fields if field not in properties]
        if missing:
            raise ValueError(f"{feature_id}: missing required fields: {', '.join(missing)}")

        normalized = _validate_common_properties(
            properties,
            feature_id=feature_id,
            expected_model_version=expected_model_version,
            expected_method_version=expected_method_version,
            expected_grid_data_version=expected_grid_data_version,
        )
        if normalized["output_id"] != expected_output_id:
            raise ValueError(f"{feature_id}: output identity drift")

        if layer_id == "grid_lines":
            normalized["model_component_name"] = _nullable_string(
                properties.get("model_component_name"), "model_component_name", feature_id
            )
            in_service = properties.get("in_service")
            if in_service is not None and not isinstance(in_service, bool):
                raise ValueError(f"{feature_id}: in_service must be boolean or null")
            if properties.get("component_type") not in {
                "lv_cable", "mv_cable", "hv_cable", "unknown_cable"
            }:
                raise ValueError(f"{feature_id}: line component type drift")
            if properties.get("evidence_status") not in {
                "registered", "registered_aggregated", "model_estimated"
            }:
                raise ValueError(f"{feature_id}: evidence status drift")
            normalized["length_km"] = _number(
                properties.get("length_km"), "length_km", feature_id, nullable=True
            )
            connected = properties.get("connected_transformer_ids")
            if not isinstance(connected, list) or not all(
                isinstance(item, str) and item for item in connected
            ):
                raise ValueError(f"{feature_id}: invalid connected transformer IDs")
            normalized["connected_transformer_ids"] = connected
            normalized["serving_transformer_id"] = _nullable_string(
                properties.get("serving_transformer_id"),
                "serving_transformer_id",
                feature_id,
            )
            for field in (
                "connected_mv_hv_transformer_ids",
                "root_bus_ids",
                "source_station_objectids",
            ):
                identifiers = properties.get(field)
                if not isinstance(identifiers, list) or not all(
                    isinstance(item, str) and item for item in identifiers
                ):
                    raise ValueError(f"{feature_id}: invalid {field}")
                normalized[field] = identifiers
            normalized["serving_mv_hv_transformer_id"] = _nullable_string(
                properties.get("serving_mv_hv_transformer_id"),
                "serving_mv_hv_transformer_id",
                feature_id,
            )
        elif layer_id == "grid_transformers":
            normalized["model_component_name"] = _nullable_string(
                properties.get("model_component_name"), "model_component_name", feature_id
            )
            in_service = properties.get("in_service")
            if in_service is not None and not isinstance(in_service, bool):
                raise ValueError(f"{feature_id}: in_service must be boolean or null")
            if properties.get("component_type") not in {
                "lv_mv_transformer", "mv_hv_transformer"
            }:
                raise ValueError(f"{feature_id}: transformer component type drift")
            if properties.get("transformer_type") not in {"lv_mv", "mv_hv"}:
                raise ValueError(f"{feature_id}: transformer type drift")
            for field in (
                "primary_nominal_voltage_kv",
                "secondary_nominal_voltage_kv",
                "rated_power_kva",
            ):
                normalized[field] = _number(
                    properties.get(field), field, feature_id, nullable=True
                )
            for field in ("source_station_objectid", "source_station_name"):
                normalized[field] = _nullable_string(
                    properties.get(field), field, feature_id
                )
            mapping_status = properties.get("upstream_mapping_status")
            if mapping_status not in {
                "available",
                "disconnected",
                "ambiguous",
                "not_applicable",
            }:
                raise ValueError(f"{feature_id}: upstream mapping status drift")
            normalized["upstream_mapping_status"] = mapping_status
            for field in (
                "upstream_mapping_method",
                "upstream_mv_hv_transformer_id",
                "upstream_root_bus_id",
                "upstream_source_station_objectid",
            ):
                normalized[field] = _nullable_string(
                    properties.get(field), field, feature_id
                )
            for field in (
                "upstream_candidate_root_bus_ids",
                "upstream_candidate_mv_hv_transformer_ids",
                "upstream_topology_path_edge_ids",
            ):
                identifiers = properties.get(field)
                if not isinstance(identifiers, list) or not all(
                    isinstance(item, str) and item for item in identifiers
                ):
                    raise ValueError(f"{feature_id}: invalid {field}")
                normalized[field] = identifiers

        else:
            reach_contract = {
                "grid_lv_mv_transformer_reach": {
                    "level": "lv_mv",
                    "voltage": "lv",
                    "method": "pc6_lv_cable_length_share_v2",
                },
                "grid_mv_hv_transformer_reach": {
                    "level": "mv_hv",
                    "voltage": "mv",
                    "method": "pc6_lv_cable_share_by_electrical_root_v2",
                },
            }[layer_id]
            level = reach_contract["level"]
            if properties.get("component_type") != f"{level}_transformer_reach":
                raise ValueError(f"{feature_id}: transformer reach component type drift")
            if (
                properties.get("transformer_type") != level
                or properties.get("reach_level") != level
                or properties.get("voltage_level") != reach_contract["voltage"]
            ):
                raise ValueError(f"{feature_id}: transformer reach level drift")
            if properties.get("reach_method") != reach_contract["method"]:
                raise ValueError(f"{feature_id}: transformer reach method drift")
            if properties.get("share_scope") != "absolute_pc6_to_target":
                raise ValueError(f"{feature_id}: transformer share scope drift")

            pc6_id = _string(properties, "pc6_id", feature_id)
            if not re.fullmatch(r"[1-9][0-9]{3}[A-Z]{2}", pc6_id):
                raise ValueError(f"{feature_id}: invalid normalized PC6 identifier")
            expected_feature_id = (
                f"grid-{level.replace('_', '-')}-transformer-reach-pc6-{pc6_id}"
            )
            if feature_id != expected_feature_id:
                raise ValueError(f"{feature_id}: PC6 reach identity drift")
            normalized["pc6_id"] = pc6_id
            normalized["reach_level"] = level
            normalized["reach_method"] = reach_contract["method"]
            normalized["share_scope"] = "absolute_pc6_to_target"

            for field in ("dominant_transformer_id", "dominant_transformer_name"):
                normalized[field] = _string(properties, field, feature_id)
            for field in (
                "runner_up_transformer_id",
                "runner_up_transformer_name",
                "ambiguity_reason",
            ):
                normalized[field] = _nullable_string(
                    properties.get(field), field, feature_id
                )
            for field in (
                "dominant_root_bus_id",
                "runner_up_root_bus_id",
                "fallback_bus_id",
            ):
                normalized[field] = _nullable_identifier(
                    properties.get(field), field, feature_id
                )

            normalized["dominant_transformer_share"] = _share(
                properties.get("dominant_transformer_share"),
                "dominant_transformer_share",
                feature_id,
            )
            normalized["dominant_transformer_share_percent"] = _share(
                properties.get("dominant_transformer_share_percent"),
                "dominant_transformer_share_percent",
                feature_id,
                percent=True,
            )
            normalized["runner_up_transformer_share"] = _share(
                properties.get("runner_up_transformer_share"),
                "runner_up_transformer_share",
                feature_id,
                nullable=True,
            )
            normalized["runner_up_transformer_share_percent"] = _share(
                properties.get("runner_up_transformer_share_percent"),
                "runner_up_transformer_share_percent",
                feature_id,
                percent=True,
                nullable=True,
            )
            normalized["share_margin"] = _share(
                properties.get("share_margin"), "share_margin", feature_id
            )
            normalized["share_margin_percentage_points"] = _share(
                properties.get("share_margin_percentage_points"),
                "share_margin_percentage_points",
                feature_id,
                percent=True,
            )
            normalized["matched_lv_cable_length_m"] = _number(
                properties.get("matched_lv_cable_length_m"),
                "matched_lv_cable_length_m",
                feature_id,
                nullable=True,
            )
            normalized["fallback_distance_m"] = _number(
                properties.get("fallback_distance_m"),
                "fallback_distance_m",
                feature_id,
                nullable=True,
            )

            entity_count = properties.get("entity_count")
            if (
                isinstance(entity_count, bool)
                or not isinstance(entity_count, int)
                or entity_count < 1
            ):
                raise ValueError(f"{feature_id}: invalid transformer share count")
            normalized["entity_count"] = entity_count
            for field in ("has_overlap", "is_ambiguous", "fallback_used"):
                normalized[field] = _boolean(properties.get(field), field, feature_id)
            if normalized["has_overlap"] != (entity_count > 1):
                raise ValueError(f"{feature_id}: transformer overlap flag drift")
            if normalized["is_ambiguous"] and not normalized["has_overlap"]:
                raise ValueError(f"{feature_id}: ambiguity requires multiple shares")

            ranked_shares = properties.get("ranked_shares")
            if not isinstance(ranked_shares, list) or len(ranked_shares) != entity_count:
                raise ValueError(f"{feature_id}: incomplete ranked transformer shares")
            share_total = 0.0
            for expected_rank, item in enumerate(ranked_shares, start=1):
                share = _mapping(item, f"{feature_id}.ranked_shares[{expected_rank}]")
                if share.get("rank") != expected_rank:
                    raise ValueError(f"{feature_id}: transformer share rank drift")
                _string(share, "transformer_id", feature_id)
                _string(share, "transformer_name", feature_id)
                expected_target_type = (
                    "lv_mv_transformer"
                    if level == "lv_mv"
                    else "mv_hv_transformer_root"
                )
                if share.get("target_type") != expected_target_type:
                    raise ValueError(f"{feature_id}: ranked transformer target drift")
                share_total += _share(
                    share.get("share"), "ranked share", feature_id
                )
                _share(
                    share.get("share_percent"),
                    "ranked share percent",
                    feature_id,
                    percent=True,
                )
                for field in (
                    "lv_mv_transformer_ids",
                    "mv_hv_transformer_ids",
                    "root_bus_ids",
                    "source_station_objectids",
                ):
                    identifiers = share.get(field)
                    if not isinstance(identifiers, list) or not all(
                        isinstance(item, str) and item for item in identifiers
                    ):
                        raise ValueError(
                            f"{feature_id}: invalid ranked {field} evidence"
                        )
                methods = share.get("match_methods")
                if not isinstance(methods, list) or not methods or not all(
                    isinstance(item, str) and item for item in methods
                ):
                    raise ValueError(f"{feature_id}: invalid ranked match methods")
            if abs(share_total - 1.0) > 0.0001:
                raise ValueError(f"{feature_id}: transformer shares do not sum to one")
            if ranked_shares[0]["transformer_id"] != properties["dominant_transformer_id"]:
                raise ValueError(f"{feature_id}: dominant transformer rank drift")
            normalized["ranked_shares"] = ranked_shares

            normalized["match_method"] = _string(
                properties, "match_method", feature_id
            )
            match_evidence = properties.get("match_evidence")
            if not isinstance(match_evidence, dict) or not match_evidence:
                raise ValueError(f"{feature_id}: invalid match evidence")
            if match_evidence.get("share_scope") != "absolute_pc6_to_target":
                raise ValueError(f"{feature_id}: match evidence share scope drift")
            normalized["match_evidence"] = match_evidence
            normalized["pc6_source_id"] = _string(
                properties, "pc6_source_id", feature_id
            )
            source_hash = _string(properties, "pc6_source_sha256", feature_id)
            if not re.fullmatch(r"[0-9a-f]{64}", source_hash):
                raise ValueError(f"{feature_id}: invalid PC6 source hash")
            normalized["pc6_source_sha256"] = source_hash
            if normalized["fallback_used"] != (
                normalized["fallback_bus_id"] is not None
                and normalized["fallback_distance_m"] is not None
            ):
                raise ValueError(f"{feature_id}: fallback evidence drift")
            if properties.get("evidence_status") != "model_estimated":
                raise ValueError(f"{feature_id}: transformer reach evidence drift")
            normalized["transformer_type"] = level
            normalized["evidence_status"] = "model_estimated"

        geometry = _validate_geometry(
            feature_document.get("geometry"),
            layer_id=layer_id,
            feature_id=feature_id,
        )
        records.append(
            GridRecord(
                layer_id=layer_id,
                properties={field: normalized[field] for field in expected_fields},
                source_feature_hash=_feature_hash(normalized, geometry),
                geometry_json=json.dumps(
                    geometry, ensure_ascii=True, separators=(",", ":")
                ),
            )
        )
        component_ids.add(feature_id)
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
        raise RuntimeError(
            f"Grid API request failed: {method} {urlparse(url).path}"
        ) from exc


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
        raise ValueError("Grid output data link must remain on the configured API origin")
    return target


def fetch_grid_artifact(
    base_url: str,
    *,
    bbox: list[float],
    expected_release_commit: str,
    expected_container_digest: str,
    expected_model_version: str,
    expected_contract_version: str,
    expected_data_mode: str,
    session: Any = requests,
    timeout: int = 1800,
) -> GridArtifact:
    base_url = base_url.rstrip("/")
    readiness = _json_response(
        _request(session, "GET", f"{base_url}/ready", timeout=30),
        "GET /ready",
    )
    if readiness.get("status") != "ready":
        raise RuntimeError("Grid API is not ready")
    grid_data_version = _string(readiness, "grid_data_version", "GET /ready")
    data_mode = _string(readiness, "data_mode", "GET /ready")
    if data_mode != expected_data_mode:
        raise ValueError("GET /ready: grid data mode drift")

    metadata = _json_response(
        _request(session, "GET", f"{base_url}/metadata", timeout=30),
        "GET /metadata",
    )
    if metadata.get("contract_version") != expected_contract_version:
        raise ValueError("GET /metadata: contract version drift")
    model = _mapping(metadata.get("model"), "GET /metadata model")
    if model.get("id") != GRID_MODEL_ID or model.get("version") != expected_model_version:
        raise ValueError("GET /metadata: model identity or version drift")
    method = _mapping(metadata.get("method"), "GET /metadata method")
    method_version = _string(method, "version", "GET /metadata method")
    release = _mapping(metadata.get("release"), "GET /metadata release")
    if release.get("git_commit") != expected_release_commit:
        raise ValueError("GET /metadata: release commit drift")
    if release.get("container_digest") != expected_container_digest:
        raise ValueError("GET /metadata: container digest drift")
    active = _mapping(metadata.get("active_grid_data"), "GET /metadata active_grid_data")
    if active.get("grid_data_version") != grid_data_version or active.get("data_mode") != data_mode:
        raise ValueError("GET /metadata: active grid data drift")

    catalog = _json_response(
        _request(session, "GET", f"{base_url}/layers", timeout=30),
        "GET /layers",
    )
    layers = catalog.get("layers")
    if not isinstance(layers, list) or {item.get("id") for item in layers} != set(GRID_LAYER_IDS):
        raise ValueError("GET /layers: grid layer set drift")
    for layer in layers:
        runtime = _mapping(layer.get("runtime"), f"GET /layers {layer.get('id')} runtime")
        count = runtime.get("feature_count")
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise ValueError(f"GET /layers: {layer.get('id')} is empty")

    run = _json_response(
        _request(
            session,
            "POST",
            f"{base_url}/runs",
            timeout=timeout,
            json={
                "operation": "export_layers",
                "selection": {"type": "bbox", "bbox": bbox},
                "layer_ids": list(GRID_LAYER_IDS),
                "voltage_levels": [],
                "component_ids": [],
            },
        ),
        "POST /runs",
    )
    if run.get("status") != "completed":
        raise RuntimeError("POST /runs did not complete")
    run_id = _string(run, "run_id", "POST /runs")
    outputs = run.get("outputs")
    if not isinstance(outputs, list) or {item.get("layer_id") for item in outputs} != set(GRID_LAYER_IDS):
        raise ValueError("POST /runs must return all grid layer outputs")

    stored_run = _json_response(
        _request(session, "GET", f"{base_url}/runs/{run_id}", timeout=30),
        "GET run",
    )
    if stored_run != run:
        raise ValueError("GET run does not match the completed run record")

    records_by_layer: dict[str, list[GridRecord]] = {}
    output_ids: dict[str, str] = {}
    for summary in outputs:
        layer_id = summary["layer_id"]
        output_id = _string(summary, "output_id", f"POST /runs {layer_id}")
        output = _json_response(
            _request(session, "GET", f"{base_url}/outputs/{output_id}", timeout=30),
            f"GET output {layer_id}",
        )
        if output.get("layer_id") != layer_id or output.get("media_type") != GRID_MEDIA_TYPE:
            raise ValueError(f"GET output: {layer_id} identity or media type drift")
        links = _mapping(output.get("links"), f"GET output {layer_id} links")
        data_url = _same_origin_url(
            base_url, _string(links, "data", f"GET output {layer_id} links")
        )
        data_response = _request(session, "GET", data_url, timeout=timeout)
        content = data_response.content
        if len(content) != output.get("byte_size"):
            raise ValueError(f"{layer_id} output byte size does not match its record")
        if hashlib.sha256(content).hexdigest() != output.get("sha256"):
            raise ValueError(f"{layer_id} output SHA-256 does not match its record")
        if data_response.headers.get("content-type", "").split(";", 1)[0] != GRID_MEDIA_TYPE:
            raise ValueError(f"{layer_id} output response media type drift")
        try:
            collection = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"{layer_id} output is not valid UTF-8 GeoJSON") from exc
        records = load_grid_records(
            collection,
            layer_id=layer_id,
            expected_model_version=expected_model_version,
            expected_method_version=method_version,
            expected_grid_data_version=grid_data_version,
            expected_output_id=output_id,
        )
        if len(records) != output.get("feature_count") or len(records) != summary.get("feature_count"):
            raise ValueError(f"{layer_id} feature count does not match its records")
        records_by_layer[layer_id] = records
        output_ids[layer_id] = output_id

    return GridArtifact(
        records_by_layer=records_by_layer,
        release_commit=expected_release_commit,
        container_digest=expected_container_digest,
        grid_data_version=grid_data_version,
        data_mode=data_mode,
        output_ids=output_ids,
    )


def get_grid_readiness_signature(
    base_url: str,
    *,
    session: Any = requests,
) -> tuple[str, str]:
    response = _json_response(
        _request(session, "GET", f"{base_url.rstrip('/')}/ready", timeout=30),
        "GET /ready",
    )
    if response.get("status") != "ready":
        raise RuntimeError("Grid API is not ready")
    return (
        _string(response, "grid_data_version", "GET /ready"),
        _string(response, "data_mode", "GET /ready"),
    )
