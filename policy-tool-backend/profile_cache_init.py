from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import os
import tempfile
import time
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin

import requests

from transformer_baseline import SCHEMA_VERSION, TransformerBaselineStore


PROFILE_YEAR = 2023
GRID_EXPORT_BBOX = [4.60, 52.50, 4.98, 52.88]
GRID_LAYERS = (
    "grid_transformers",
    "grid_lv_mv_transformer_reach",
    "grid_mv_hv_transformer_reach",
)
PV_SCENARIO = "koersvaste_middenweg"
PV_PROFILE_START = "2024-01-01T00:00:00Z"
PV_PROFILE_END = "2025-01-01T00:00:00Z"
LIMITATIONS = [
    {
        "code": "pv_weather_calendar_projected_to_2023",
        "description": (
            "PV uses its native 2024 reference-weather sequence with 29 February removed; "
            "the remaining PT15M values are projected by ordinal interval onto the fixed "
            "Consumption 2023 profile calendar. This is a temporary baseline alignment, "
            "not an observed same-year demand-production pairing."
        ),
    },
    {
        "code": "compact_consumption_cache_adapter",
        "description": (
            "The initializer reads the accepted compact Consumption source-cache recipe "
            "from its read-only model volume because the current model API does not yet "
            "publish compact whole-layer profile recipes."
        ),
    },
    {
        "code": "baseline_models_only",
        "description": (
            "Transformer totals currently contain residential PC6 electricity demand and "
            "CBS-buurt PV production. EV, wind, heat, commercial and industrial profiles "
            "remain excluded until those models expose compatible profile contracts."
        ),
    },
    {
        "code": "temporary_policy_tool_cache_ownership",
        "description": (
            "The policy-tool integration currently builds and serves the transformer "
            "baseline cache. The professional architecture should move this persistent "
            "aggregation capability behind the congestion-model service contract."
        ),
    },
]


class CacheBuildError(RuntimeError):
    pass


class JsonClient:
    def __init__(self, base_url: str, timeout: float = 180.0) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout = timeout
        self.session = requests.Session()

    def json(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = self.session.request(
            method,
            urljoin(self.base_url, path.lstrip("/")),
            timeout=self.timeout,
            **kwargs,
        )
        response.raise_for_status()
        value = response.json()
        if not isinstance(value, dict):
            raise CacheBuildError(f"{method} {path} did not return an object")
        return value

    def bytes(self, path: str) -> bytes:
        response = self.session.get(
            urljoin(self.base_url, path.lstrip("/")), timeout=self.timeout
        )
        response.raise_for_status()
        return response.content


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def source_identity(
    consumption_root: Path,
    grid: JsonClient,
    pv: JsonClient,
    *,
    pv_metadata: dict[str, Any] | None = None,
    pv_capacity_output: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = _read_json(consumption_root / "state.json")
    grid_ready = grid.json("GET", "/ready")
    pv_ready = pv.json("GET", "/ready")
    if pv_metadata is None or pv_capacity_output is None:
        pv_metadata, pv_capacity_output = _resolve_pv_capacity_output(pv)
    return {
        "consumption": {
            "dataset_id": state.get("dataset_id"),
            "state_fingerprint": state.get("state_fingerprint"),
            "source_cache_sha256": state.get("source_cache_sha256"),
            "profile_feature_count": state.get("residential_pc6_profile_feature_count"),
        },
        "grid": {
            "model_version": grid_ready.get("model_version"),
            "grid_data_version": grid_ready.get("grid_data_version"),
            "release_commit": grid_ready.get("release_commit"),
            "container_digest": grid_ready.get("container_digest"),
            "data_mode": grid_ready.get("data_mode"),
        },
        "pv": {
            "model_version": pv_ready.get("model_version"),
            "config_fingerprint": pv_ready.get("config_fingerprint"),
            "release_commit": pv_metadata.get("release_commit"),
            "container_image": pv_metadata.get("container_image"),
            "capacity_output_id": pv_capacity_output.get("output_id"),
            "capacity_artifact_sha256": pv_capacity_output.get("artifact_sha256")
            or pv_capacity_output.get("sha256"),
        },
    }


def initialize(
    *,
    output_path: Path,
    consumption_root: Path,
    grid_url: str,
    pv_url: str,
    reuse_ready_cache: bool,
) -> None:
    grid = JsonClient(grid_url)
    pv = JsonClient(pv_url, timeout=600.0)
    pv_metadata, pv_capacity_output = _resolve_pv_capacity_output(pv)
    identity = source_identity(
        consumption_root,
        grid,
        pv,
        pv_metadata=pv_metadata,
        pv_capacity_output=pv_capacity_output,
    )
    if reuse_ready_cache and _cache_matches(output_path, identity):
        print("Transformer profile baseline is current; reused persisted cache.", flush=True)
        return

    print("[1/5] Reading the compact Consumption profile inputs...", flush=True)
    timestamps, demand_shape, consumption_profiles = _consumption_inputs(consumption_root)
    print("[2/5] Exporting the existing Grid layers (no Grid rebuild)...", flush=True)
    grid_layers = _export_grid_layers(grid)
    consumption_sources, target_names = _reach_assignments(grid_layers)
    print("[3/5] Deriving the two shared full-year PV shapes...", flush=True)
    pv_inputs = _pv_inputs(
        pv,
        metadata=pv_metadata,
        capacity_output=pv_capacity_output,
    )
    print("[4/5] Asking Grid to assign PV buurten to transformer hierarchies...", flush=True)
    pv_sources = _pv_assignments(grid, pv_inputs)

    targets = {
        "lv_mv": defaultdict(_empty_target),
        "mv_hv": defaultdict(_empty_target),
    }
    sources: dict[str, dict[str, Any]] = {"pc6": {}, "cbs_buurt": {}}

    for pc6, profile in consumption_profiles.items():
        assignment = consumption_sources.get(pc6)
        if assignment is None:
            continue
        sources["pc6"][pc6] = assignment
        for stage_id in ("lv_mv", "mv_hv"):
            for share in assignment[stage_id]:
                target = targets[stage_id][share["transformer_id"]]
                target["transformer_name"] = share.get("transformer_name") or target_names.get(
                    share["transformer_id"], share["transformer_id"]
                )
                target["demand_annual_kwh"] += profile["annual_anchor_kwh"] * share["share"]
                target["consumption_ids"].add(pc6)

    pv_features = pv_inputs["features"]
    for buurt_code, assignment in pv_sources.items():
        feature = pv_features.get(buurt_code)
        if feature is None:
            continue
        sources["cbs_buurt"][buurt_code] = assignment
        for stage_id in ("lv_mv", "mv_hv"):
            for share in assignment[stage_id]:
                target = targets[stage_id][share["transformer_id"]]
                target["transformer_name"] = target_names.get(
                    share["transformer_id"], share["transformer_id"]
                )
                target["pv_residential_kwp"] += (
                    feature["scenario_residential_capacity_kwp"] * share["share"]
                )
                target["pv_commercial_kwp"] += (
                    feature["commercial_capacity_kwp"] * share["share"]
                )
                target["pv_ids"].add(buurt_code)

    normalized_targets = {
        stage_id: {
            transformer_id: _normalize_target(target)
            for transformer_id, target in sorted(stage_targets.items())
        }
        for stage_id, stage_targets in targets.items()
    }
    document: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "profile_year": PROFILE_YEAR,
        "resolution": "PT15M",
        "start": timestamps[0],
        "end": "2023-12-31T23:00:00Z",
        "timestamps": timestamps,
        "shapes": {
            "demand_kw_per_kwh": demand_shape,
            "pv_residential_kw_per_kwp": pv_inputs["residential_shape"],
            "pv_commercial_kw_per_kwp": pv_inputs["commercial_shape"],
        },
        "sources": sources,
        "targets": normalized_targets,
        "overall_datacompleetheid": 1,
        "source_models": [
            {"model": "consumption", **identity["consumption"]},
            {"model": "pv", **identity["pv"]},
            {"model": "grid", **identity["grid"]},
        ],
        "input_identity": identity,
        "limitations": LIMITATIONS,
    }
    document["cache_fingerprint"] = hashlib.sha256(canonical_bytes(document)).hexdigest()
    TransformerBaselineStore._validate(document)
    print("[5/5] Persisting the compact transformer baseline...", flush=True)
    _write_gzip_atomic(output_path, document)
    print(
        "Transformer profile baseline created: "
        f"pc6={len(sources['pc6'])} pv={len(sources['cbs_buurt'])} "
        f"lv_mv={len(normalized_targets['lv_mv'])} mv_hv={len(normalized_targets['mv_hv'])}",
        flush=True,
    )


def _consumption_inputs(
    consumption_root: Path,
) -> tuple[list[str], list[float], dict[str, dict[str, Any]]]:
    state = _read_json(consumption_root / "state.json")
    dataset_dir = consumption_root / str(state["dataset_directory"])
    manifest = _read_json(dataset_dir / "source-cache-manifest.json")
    layer = manifest["layers"]["residential_electricity_pc6_profiles_pt15m"]
    profiles = {
        value["spatial_unit_code"]: value
        for value in layer["feature_profiles"].values()
        if isinstance(value, dict) and value.get("spatial_unit_code")
    }
    archive_path = consumption_root / "source-artifacts" / f"{state['source_cache_sha256']}.zip"
    shape_path = layer["shape"]["data_path"]
    timestamps: list[str] = []
    shape: list[float] = []
    with zipfile.ZipFile(archive_path) as archive:
        with archive.open(shape_path) as raw:
            reader = csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8"))
            for row in reader:
                timestamps.append(_iso_z(row["interval_start_utc"]))
                shape.append(float(row["unit_annual_fraction"]) / 0.25)
    if len(timestamps) != 35040 or len(shape) != 35040:
        raise CacheBuildError("Consumption compact profile is not one PT15M year")
    return timestamps, shape, profiles


def _export_grid_layers(grid: JsonClient) -> dict[str, dict[str, Any]]:
    run = grid.json(
        "POST",
        "/runs",
        json={
            "operation": "export_layers",
            "selection": {"type": "bbox", "bbox": GRID_EXPORT_BBOX},
            "layer_ids": list(GRID_LAYERS),
            "voltage_levels": [],
            "component_ids": [],
        },
    )
    if run.get("status") != "completed":
        raise CacheBuildError("Grid layer export did not complete")
    documents: dict[str, dict[str, Any]] = {}
    for summary in run.get("outputs", []):
        layer_id = summary.get("layer_id")
        if layer_id not in GRID_LAYERS:
            continue
        output_id = summary["output_id"]
        metadata = grid.json("GET", f"/outputs/{output_id}")
        data_path = metadata.get("links", {}).get("data", f"/outputs/{output_id}/data")
        documents[layer_id] = json.loads(grid.bytes(data_path))
    if set(documents) != set(GRID_LAYERS):
        raise CacheBuildError("Grid export omitted required transformer layers")
    return documents


def _reach_assignments(
    layers: dict[str, dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    target_names: dict[str, str] = {}
    for feature in layers["grid_transformers"]["features"]:
        properties = feature["properties"]
        target_id = properties.get("component_id")
        if target_id:
            target_names[target_id] = str(
                properties.get("transformer_name")
                or properties.get("name")
                or properties.get("source_station_name")
                or target_id
            )
    sources: dict[str, dict[str, Any]] = {}
    for stage_id, layer_id in (
        ("lv_mv", "grid_lv_mv_transformer_reach"),
        ("mv_hv", "grid_mv_hv_transformer_reach"),
    ):
        for feature in layers[layer_id]["features"]:
            properties = feature["properties"]
            pc6 = str(properties.get("pc6_id", "")).upper()
            if not pc6:
                continue
            raw_shares = properties.get("ranked_shares")
            shares = json.loads(raw_shares) if isinstance(raw_shares, str) else raw_shares
            if not isinstance(shares, list) or not shares:
                continue
            normalized = []
            for item in shares:
                target_id = str(item["transformer_id"])
                target_name = str(item.get("transformer_name") or target_id)
                target_names[target_id] = target_name
                normalized.append(
                    {
                        "transformer_id": target_id,
                        "transformer_name": target_name,
                        "share": float(item["share"]),
                    }
                )
            sources.setdefault(pc6, {"lv_mv": [], "mv_hv": []})[stage_id] = normalized
    return {
        source_id: stages
        for source_id, stages in sources.items()
        if stages["lv_mv"] and stages["mv_hv"]
    }, target_names


def _resolve_pv_capacity_output(
    pv: JsonClient,
    *,
    wait_seconds: float = 15.0,
) -> tuple[dict[str, Any], dict[str, Any]]:
    deadline = time.monotonic() + wait_seconds
    announced_wait = False
    while True:
        metadata = pv.json("GET", "/metadata")
        latest_path = metadata.get("links", {}).get("latest_output")
        if isinstance(latest_path, str):
            return metadata, pv.json("GET", latest_path)
        if time.monotonic() >= deadline:
            break
        if not announced_wait:
            print(
                "Waiting briefly for the initial PV capacity output from the layer publisher...",
                flush=True,
            )
            announced_wait = True
        time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))

    print("PV capacity output is absent; creating the standard all-feature output...", flush=True)
    run = pv.json(
        "POST",
        "/runs",
        json={"spatial_selection": {"type": "all"}, "parameters": {}},
    )
    output_ids = run.get("output_ids")
    if run.get("status") != "succeeded" or not isinstance(output_ids, list) or len(output_ids) != 1:
        raise CacheBuildError("PV capacity run did not produce exactly one output")
    output_id = output_ids[0]
    if not isinstance(output_id, str) or not output_id:
        raise CacheBuildError("PV capacity run returned an invalid output identity")
    return pv.json("GET", "/metadata"), pv.json("GET", f"/outputs/{output_id}")


def _pv_inputs(
    pv: JsonClient,
    *,
    metadata: dict[str, Any],
    capacity_output: dict[str, Any],
) -> dict[str, Any]:
    capacity_path = capacity_output.get("links", {}).get("data")
    capacity = json.loads(pv.bytes(capacity_path))
    features: dict[str, dict[str, Any]] = {}
    geometries: dict[str, dict[str, Any]] = {}
    for feature in capacity["features"]:
        properties = feature["properties"]
        source_id = str(properties["source_feature_id"])
        features[source_id] = {
            "base_residential_capacity_kwp": float(properties["residential_kwp_real"]),
            "commercial_capacity_kwp": float(properties["commercial_kwp_derived"]),
            "source_feature_version": str(
                properties.get("source_feature_hash")
                or properties.get("capacity_version")
                or capacity_output.get("artifact_sha256")
                or capacity_output.get("sha256")
            ),
        }
        geometries[source_id] = feature["geometry"]
    first_id, second_id = _independent_capacity_pair(features)
    run = pv.json(
        "POST",
        "/runs",
        json={
            "output_type": "production_profile",
            "spatial_selection": {
                "type": "cbs_buurt",
                "feature_ids": [first_id, second_id],
            },
            "time_window": {
                "start": PV_PROFILE_START,
                "end_exclusive": PV_PROFILE_END,
            },
            "scenario": PV_SCENARIO,
            "scenario_year": 2035,
            "profile_calendar": 2024,
            "parameters": {},
        },
    )
    output_id = run["output_ids"][0]
    output = pv.json("GET", f"/outputs/{output_id}")
    rows = list(csv.DictReader(io.StringIO(pv.bytes(output["links"]["data"]).decode("utf-8"))))
    by_feature: dict[str, list[float]] = defaultdict(list)
    timestamps: list[str] = []
    for row in rows:
        by_feature[row["source_feature_id"]].append(float(row["pv_ac_generation_kw"]))
        if row["source_feature_id"] == first_id:
            timestamps.append(row["interval_start_utc"])
    profile_records = {
        item["source_feature_id"]: item
        for item in output["profile_metadata"]["profiles"]
    }
    first = profile_records[first_id]
    second = profile_records[second_id]
    r1 = float(first["scenario_residential_capacity_kwp"])
    c1 = float(first["commercial_capacity_kwp"])
    r2 = float(second["scenario_residential_capacity_kwp"])
    c2 = float(second["commercial_capacity_kwp"])
    determinant = r1 * c2 - r2 * c1
    if abs(determinant) < 1e-9:
        raise CacheBuildError("PV reference features are not linearly independent")
    residential_shape = []
    commercial_shape = []
    for first_value, second_value in zip(by_feature[first_id], by_feature[second_id]):
        residential_shape.append(max(0.0, (first_value * c2 - second_value * c1) / determinant))
        commercial_shape.append(max(0.0, (r1 * second_value - r2 * first_value) / determinant))
    keep = [
        index
        for index, timestamp in enumerate(timestamps)
        if not timestamp.startswith("2024-02-29")
    ]
    if len(keep) != 35040:
        raise CacheBuildError("PV 2024 projection did not produce one non-leap PT15M year")
    multiplier = r1 / float(first["base_residential_capacity_kwp"])
    for feature in features.values():
        feature["scenario_residential_capacity_kwp"] = (
            feature["base_residential_capacity_kwp"] * multiplier
        )
    return {
        "features": features,
        "geometries": geometries,
        "residential_shape": [residential_shape[index] for index in keep],
        "commercial_shape": [commercial_shape[index] for index in keep],
        "model_id": metadata["model_id"],
        "model_version": metadata["model_version"],
        "release_commit": metadata["release_commit"],
        "artifact_sha256": capacity_output.get("artifact_sha256")
        or capacity_output.get("sha256"),
    }


def _pv_assignments(grid: JsonClient, pv_inputs: dict[str, Any]) -> dict[str, dict[str, Any]]:
    geometries = pv_inputs["geometries"]
    bbox = _geometry_bbox(geometries.values())
    artifact_sha = str(pv_inputs["artifact_sha256"])
    run = grid.json(
        "POST",
        "/runs",
        json={
            "operation": "assign_feature_hierarchy",
            "hierarchy_policy": "nearest_electrical_root_v1",
            "selection": {"type": "bbox", "bbox": bbox},
            "source": {
                "source_model_id": pv_inputs["model_id"],
                "source_model_version": pv_inputs["model_version"],
                "source_layer_id": "pv_capacity",
                "source_layer_version": artifact_sha,
                "source_release_id": pv_inputs["release_commit"],
                "source_artifact_sha256": artifact_sha,
            },
            "features": [
                {
                    "source_feature_id": source_id,
                    "source_feature_type": "cbs_buurt",
                    "source_feature_version": pv_inputs["features"][source_id][
                        "source_feature_version"
                    ],
                    "geometry": geometry,
                }
                for source_id, geometry in sorted(geometries.items())
            ],
        },
    )
    if run.get("status") != "completed":
        raise CacheBuildError("PV Grid assignment did not complete")
    output_id = run["outputs"][0]["output_id"]
    output = grid.json("GET", f"/outputs/{output_id}")
    data_path = output.get("links", {}).get("data", f"/outputs/{output_id}/data")
    document = json.loads(grid.bytes(data_path))
    sources: dict[str, dict[str, Any]] = {}
    for feature in document["features"]:
        properties = feature["properties"]
        row_type = properties.get("row_type")
        source_id = properties.get("source_feature_id")
        if source_id not in geometries or properties.get("assignment_status") != "assigned":
            continue
        if row_type == "source_to_lv_mv_assignment":
            stage_id = "lv_mv"
            transformer_id = properties["lv_mv_transformer_id"]
        elif row_type == "source_to_mv_hv_derived":
            stage_id = "mv_hv"
            transformer_id = properties["mv_hv_endpoint_id"]
        else:
            continue
        sources.setdefault(source_id, {"lv_mv": [], "mv_hv": []})[stage_id].append(
            {"transformer_id": transformer_id, "share": float(properties["share"])}
        )
    return {
        source_id: stages
        for source_id, stages in sources.items()
        if stages["lv_mv"] and stages["mv_hv"]
    }


def _independent_capacity_pair(features: dict[str, dict[str, Any]]) -> tuple[str, str]:
    ordered = sorted(features)
    for index, first_id in enumerate(ordered):
        first = features[first_id]
        for second_id in ordered[index + 1 :]:
            second = features[second_id]
            determinant = (
                first["base_residential_capacity_kwp"] * second["commercial_capacity_kwp"]
                - second["base_residential_capacity_kwp"] * first["commercial_capacity_kwp"]
            )
            if abs(determinant) > 1e-6:
                return first_id, second_id
    raise CacheBuildError("PV capacity result has no independent residential/commercial pair")


def _geometry_bbox(geometries: Iterable[dict[str, Any]]) -> list[float]:
    points: list[tuple[float, float]] = []

    def visit(value: Any) -> None:
        if (
            isinstance(value, list)
            and len(value) >= 2
            and isinstance(value[0], (int, float))
            and isinstance(value[1], (int, float))
        ):
            points.append((float(value[0]), float(value[1])))
        elif isinstance(value, list):
            for item in value:
                visit(item)

    for geometry in geometries:
        visit(geometry.get("coordinates"))
    if not points:
        raise CacheBuildError("PV capacity geometries are empty")
    return [
        min(point[0] for point in points),
        min(point[1] for point in points),
        max(point[0] for point in points),
        max(point[1] for point in points),
    ]


def _empty_target() -> dict[str, Any]:
    return {
        "transformer_name": "",
        "demand_annual_kwh": 0.0,
        "pv_residential_kwp": 0.0,
        "pv_commercial_kwp": 0.0,
        "consumption_ids": set(),
        "pv_ids": set(),
    }


def _normalize_target(target: dict[str, Any]) -> dict[str, Any]:
    return {
        "transformer_name": target["transformer_name"],
        "demand_annual_kwh": target["demand_annual_kwh"],
        "pv_residential_kwp": target["pv_residential_kwp"],
        "pv_commercial_kwp": target["pv_commercial_kwp"],
        "datacompleetheid": 1,
        "contributor_counts": {
            "consumption_pc6": len(target["consumption_ids"]),
            "pv_cbs_buurt": len(target["pv_ids"]),
        },
    }


def _cache_matches(path: Path, identity: dict[str, Any]) -> bool:
    if not path.exists():
        return False
    try:
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8") as handle:
            document = json.load(handle)
        TransformerBaselineStore._validate(document)
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    return document.get("input_identity") == identity


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CacheBuildError(f"Expected JSON object: {path}")
    return value


def _iso_z(value: str) -> str:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat().replace(
        "+00:00", "Z"
    )


def _write_gzip_atomic(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with gzip.open(temporary, "wt", encoding="utf-8", compresslevel=6) as handle:
            json.dump(document, handle, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the fixed 2023 transformer baseline")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--consumption-root", type=Path, required=True)
    parser.add_argument("--grid-url", required=True)
    parser.add_argument("--pv-url", required=True)
    parser.add_argument("--reuse-ready-cache", action="store_true")
    args = parser.parse_args()
    initialize(
        output_path=args.output,
        consumption_root=args.consumption_root,
        grid_url=args.grid_url,
        pv_url=args.pv_url,
        reuse_ready_cache=args.reuse_ready_cache,
    )


if __name__ == "__main__":
    main()
