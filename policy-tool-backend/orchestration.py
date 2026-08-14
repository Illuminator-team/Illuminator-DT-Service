from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Mapping

import requests


PT15M = timedelta(minutes=15)
PC6_PATTERN = re.compile(r"^[1-9][0-9]{3}[A-Z]{2}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
CONSUMPTION_LAYER_ID = "residential_electricity_pc6_profiles_pt15m"
CONSUMPTION_MODEL_ID = "consumption-map"
CONSUMPTION_MODEL_VERSION = "0.4.0"
CONSUMPTION_RELEASE_COMMIT = "e5f44368b01bee9f4a77a409e6894f22f57f9684"
GRID_HIERARCHY_POLICY = "nearest_electrical_root_v1"
PROVISIONAL_AGGREGATION_MODE = "two_stage_provisional_estimated"


class OrchestrationError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        service: str | None = None,
        status_code: int = 502,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.service = service
        self.status_code = status_code

    def as_detail(self) -> dict[str, Any]:
        detail: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.service is not None:
            detail["service"] = self.service
        return detail


@dataclass(frozen=True)
class CompletedRun:
    run_id: str
    output_id: str
    record: dict[str, Any]


@dataclass(frozen=True)
class ConsumptionProfileIdentity:
    model_id: str
    model_version: str
    layer_id: str
    layer_version: str
    profile_id: str
    profile_version: str
    release_commit: str


class ModelApiClient:
    def __init__(
        self,
        base_url: str,
        service_name: str,
        *,
        session: requests.Session | None = None,
        request_timeout: float = 30.0,
        poll_attempts: int = 20,
        poll_interval: float = 0.25,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.service_name = service_name
        self.session = session or requests.Session()
        self.request_timeout = request_timeout
        self.poll_attempts = poll_attempts
        self.poll_interval = poll_interval
        self.sleeper = sleeper

    def create_completed_run(self, payload: Mapping[str, Any]) -> CompletedRun:
        record = self._json_request("POST", "/runs", json=dict(payload))
        run_id = self._required_string(record, "run_id", "run response")

        for attempt in range(self.poll_attempts + 1):
            status = record.get("status")
            if status == "completed":
                return self._completed_run(record, run_id)
            if status == "failed":
                raise OrchestrationError(
                    "upstream_run_failed",
                    f"{self.service_name} could not complete the requested run.",
                    service=self.service_name,
                )
            if status not in {"submitted", "running"}:
                raise self._contract_error("run response has an invalid status")
            if attempt == self.poll_attempts:
                break
            self.sleeper(self.poll_interval)
            record = self._json_request("GET", f"/runs/{run_id}")

        raise OrchestrationError(
            "upstream_run_timeout",
            f"{self.service_name} did not complete within the configured polling window.",
            service=self.service_name,
            status_code=504,
        )

    def get_verified_json_output(self, output_id: str) -> dict[str, Any]:
        metadata = self._json_request("GET", f"/outputs/{output_id}")
        if metadata.get("output_id") != output_id:
            raise self._contract_error("output metadata identity does not match the request")
        if metadata.get("media_type") != "application/json":
            raise self._contract_error("output is not application/json")

        document = self._json_request("GET", f"/outputs/{output_id}/data")
        canonical = json.dumps(
            document,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        expected_sha = metadata.get("sha256")
        expected_size = metadata.get("byte_size")
        if expected_sha != hashlib.sha256(canonical).hexdigest():
            raise self._contract_error("output checksum verification failed")
        if expected_size != len(canonical):
            raise self._contract_error("output byte-size verification failed")
        return document

    def get_consumption_profile_identity(
        self,
        *,
        pc6: str,
        profile_id: str,
        start: datetime,
        end: datetime,
    ) -> ConsumptionProfileIdentity:
        feature_id = f"consumption-residential-electricity-pc6-{pc6.lower()}"
        payload = {
            "dataset_id": "alkmaar_2023",
            "layer_ids": [CONSUMPTION_LAYER_ID],
            "selection": {"feature_ids": [feature_id]},
            "time": {
                "start": iso_z(start),
                "end_exclusive": iso_z(end),
                "resolution": "PT15M",
            },
        }
        run = self._json_request("POST", "/runs", json=payload)
        if run.get("status") != "succeeded":
            raise self._contract_error("profile run did not succeed synchronously")
        run_id = self._required_string(run, "run_id", "profile run")
        output_ids = run.get("output_ids")
        if (
            not isinstance(output_ids, list)
            or len(output_ids) != 1
            or not isinstance(output_ids[0], str)
            or not output_ids[0]
        ):
            raise self._contract_error("profile run must contain exactly one output ID")
        output_id = output_ids[0]
        metadata = self._json_request("GET", f"/outputs/{output_id}")
        expected_interval_count = int((end - start) / PT15M)
        if (
            metadata.get("output_id") != output_id
            or metadata.get("run_id") != run_id
            or metadata.get("status") != "available"
            or metadata.get("layer_id") != CONSUMPTION_LAYER_ID
            or metadata.get("media_type") != "application/json"
            or metadata.get("data_url") != f"/outputs/{output_id}/data"
            or metadata.get("profile_count") != 1
            or metadata.get("interval_count_per_profile")
            != expected_interval_count
            or metadata.get("value_count") != expected_interval_count
        ):
            raise self._contract_error("profile output metadata is inconsistent")

        document = self._json_request("GET", f"/outputs/{output_id}/data")
        canonical = (
            json.dumps(
                document,
                ensure_ascii=True,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
        if metadata.get("semantic_sha256") != hashlib.sha256(canonical).hexdigest():
            raise self._contract_error("profile output checksum verification failed")
        if (
            document.get("metadata_contract_version") != "reformers-consumption-v1"
            or document.get("model_id") != CONSUMPTION_MODEL_ID
            or document.get("model_version") != CONSUMPTION_MODEL_VERSION
            or document.get("dataset_id") != "alkmaar_2023"
            or document.get("layer_id") != CONSUMPTION_LAYER_ID
            or document.get("interval_count_per_profile")
            != expected_interval_count
        ):
            raise self._contract_error("profile identity is incompatible")
        requested_period = document.get("requested_period")
        if (
            not isinstance(requested_period, dict)
            or not same_instant(requested_period.get("start_inclusive"), start)
            or not same_instant(requested_period.get("end_exclusive"), end)
            or requested_period.get("resolution") != "PT15M"
            or requested_period.get("interval_semantics")
            != "start_inclusive_end_exclusive"
            or requested_period.get("interval_count") != expected_interval_count
        ):
            raise self._contract_error("profile output time window drifted")
        layer_version = document.get("layer_version")
        if not isinstance(layer_version, str) or not SHA256_PATTERN.fullmatch(
            layer_version
        ):
            raise self._contract_error("profile layer version is invalid")
        profiles = document.get("profiles")
        matches = (
            [
                item
                for item in profiles
                if isinstance(item, dict)
                and item.get("feature_id") == feature_id
                and item.get("spatial_unit_code") == pc6
                and item.get("profile_id") == profile_id
            ]
            if isinstance(profiles, list)
            else []
        )
        if len(matches) != 1:
            raise self._contract_error("requested profile identity is missing")
        intervals = matches[0].get("intervals")
        if not isinstance(intervals, list) or len(intervals) != expected_interval_count:
            raise self._contract_error("requested profile interval count drifted")
        profile_version = matches[0].get("profile_version")
        if not isinstance(profile_version, str) or not SHA256_PATTERN.fullmatch(
            profile_version
        ):
            raise self._contract_error("profile version is invalid")
        provenance = document.get("provenance")
        if not isinstance(provenance, dict):
            raise self._contract_error("profile provenance is missing")
        release_commit = provenance.get("release_commit")
        if (
            release_commit != CONSUMPTION_RELEASE_COMMIT
            or not isinstance(release_commit, str)
            or not GIT_SHA_PATTERN.fullmatch(release_commit)
            or provenance.get("profile_source_artifact_semantic_sha256")
            != layer_version
        ):
            raise self._contract_error("profile provenance identity drifted")
        return ConsumptionProfileIdentity(
            model_id=CONSUMPTION_MODEL_ID,
            model_version=CONSUMPTION_MODEL_VERSION,
            layer_id=CONSUMPTION_LAYER_ID,
            layer_version=layer_version,
            profile_id=profile_id,
            profile_version=profile_version,
            release_commit=release_commit,
        )

    def _completed_run(self, record: dict[str, Any], run_id: str) -> CompletedRun:
        outputs = record.get("outputs")
        if not isinstance(outputs, list) or len(outputs) != 1:
            raise self._contract_error("completed run must contain exactly one output")
        output = outputs[0]
        if not isinstance(output, dict):
            raise self._contract_error("completed run output is not an object")
        output_id = self._required_string(output, "output_id", "completed run output")
        return CompletedRun(run_id=run_id, output_id=output_id, record=record)

    def _json_request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = self.session.request(
                method,
                f"{self.base_url}{path}",
                timeout=self.request_timeout,
                **kwargs,
            )
            response.raise_for_status()
            document = response.json()
        except requests.Timeout as exc:
            raise OrchestrationError(
                "upstream_request_timeout",
                f"{self.service_name} did not answer in time.",
                service=self.service_name,
                status_code=504,
            ) from exc
        except (requests.RequestException, json.JSONDecodeError, ValueError) as exc:
            raise OrchestrationError(
                "upstream_request_failed",
                f"{self.service_name} returned an unsuccessful response.",
                service=self.service_name,
            ) from exc
        if not isinstance(document, dict):
            raise self._contract_error("response body is not a JSON object")
        return document

    def _contract_error(self, reason: str) -> OrchestrationError:
        return OrchestrationError(
            "upstream_contract_invalid",
            f"{self.service_name} {reason}.",
            service=self.service_name,
        )

    def _required_string(
        self, document: Mapping[str, Any], field: str, context: str
    ) -> str:
        value = document.get(field)
        if not isinstance(value, str) or not value:
            raise self._contract_error(f"{context} is missing {field}")
        return value


class TransformerProfileOrchestrator:
    def __init__(
        self,
        *,
        consumption_client: ModelApiClient,
        grid_client: ModelApiClient,
        congestion_client: ModelApiClient,
        pc6_geometry_path: Path,
    ) -> None:
        self.consumption_client = consumption_client
        self.grid_client = grid_client
        self.congestion_client = congestion_client
        self.pc6_geometry_path = pc6_geometry_path

    def aggregate_pc6(
        self,
        pc6: str,
        *,
        start: datetime,
        end: datetime,
    ) -> dict[str, Any]:
        normalized_pc6 = normalize_pc6(pc6)
        start_utc, end_utc = validate_window(start, end)
        geometry, artifact_sha256 = load_pc6_geometry(
            self.pc6_geometry_path, normalized_pc6
        )
        selection_bbox = geometry_bbox(geometry)
        profile_id = residential_pc6_profile_id(normalized_pc6)
        profile_identity = self.consumption_client.get_consumption_profile_identity(
            pc6=normalized_pc6,
            profile_id=profile_id,
            start=start_utc,
            end=end_utc,
        )

        grid_payload = {
            "operation": "assign_feature_hierarchy",
            "hierarchy_policy": GRID_HIERARCHY_POLICY,
            "selection": {"type": "bbox", "bbox": selection_bbox},
            "source": {
                "source_model_id": profile_identity.model_id,
                "source_model_version": profile_identity.model_version,
                "source_layer_id": profile_identity.layer_id,
                "source_layer_version": profile_identity.layer_version,
                "source_release_id": profile_identity.release_commit,
                "source_artifact_sha256": profile_identity.layer_version,
            },
            "features": [
                {
                    "source_feature_id": normalized_pc6,
                    "source_feature_type": "pc6",
                    "source_feature_version": profile_identity.profile_version,
                    "geometry": geometry,
                }
            ],
        }
        grid_run = self.grid_client.create_completed_run(grid_payload)

        congestion_payload = {
            "aggregation_mode": "two_stage_authoritative",
            "hierarchy_policy": GRID_HIERARCHY_POLICY,
            "target_level": "mv_hv_transformer",
            "persistence": "none",
            "grid_assignment_output_id": grid_run.output_id,
            "profiles": [
                {
                    "model_id": CONSUMPTION_MODEL_ID,
                    "layer_id": CONSUMPTION_LAYER_ID,
                    "feature_type": "pc6",
                    "source_feature_id": normalized_pc6,
                    "profile_id": profile_id,
                    "start": iso_z(start_utc),
                    "end": iso_z(end_utc),
                }
            ],
        }
        congestion_run = self.congestion_client.create_completed_run(congestion_payload)
        result = self.congestion_client.get_verified_json_output(
            congestion_run.output_id
        )
        if result.get("aggregation_mode") != PROVISIONAL_AGGREGATION_MODE:
            raise OrchestrationError(
                "upstream_contract_invalid",
                "congestion returned an unexpected hierarchy authority mode.",
                service="congestion",
            )
        completeness = result.get("overall_datacompleetheid")
        if (
            not isinstance(completeness, int)
            or isinstance(completeness, bool)
            or not 0 <= completeness <= 1
        ):
            raise OrchestrationError(
                "upstream_contract_invalid",
                "congestion returned invalid provisional datacompleetheid.",
                service="congestion",
            )

        return {
            "status": "completed",
            "feature": {
                "feature_type": "pc6",
                "source_feature_id": normalized_pc6,
                "geometry_source": {
                    "model_id": "legacy-policy-tool",
                    "layer_id": "policy_tool_pc6_energy",
                    "reference_year": 2023,
                    "artifact_sha256": artifact_sha256,
                },
            },
            "profile": {
                "model_id": CONSUMPTION_MODEL_ID,
                "model_version": profile_identity.model_version,
                "release_commit": profile_identity.release_commit,
                "layer_id": CONSUMPTION_LAYER_ID,
                "layer_version": profile_identity.layer_version,
                "profile_id": profile_id,
                "profile_version": profile_identity.profile_version,
                "start": iso_z(start_utc),
                "end": iso_z(end_utc),
                "resolution": "PT15M",
            },
            "grid_assignment": {
                "run_id": grid_run.run_id,
                "output_id": grid_run.output_id,
                "operation": "assign_feature_hierarchy",
                "hierarchy_policy": GRID_HIERARCHY_POLICY,
            },
            "congestion_aggregation": {
                "run_id": congestion_run.run_id,
                "output_id": congestion_run.output_id,
                "aggregation_mode": PROVISIONAL_AGGREGATION_MODE,
                "hierarchy_policy": GRID_HIERARCHY_POLICY,
            },
            "result": result,
        }


def normalize_pc6(value: str) -> str:
    normalized = value.replace(" ", "").upper()
    if not PC6_PATTERN.fullmatch(normalized):
        raise OrchestrationError(
            "invalid_pc6", "PC6 must contain four digits followed by two letters.", status_code=422
        )
    return normalized


def validate_window(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    if start.tzinfo is None or start.utcoffset() is None:
        raise OrchestrationError(
            "invalid_time_window", "start must include a timezone.", status_code=422
        )
    if end.tzinfo is None or end.utcoffset() is None:
        raise OrchestrationError(
            "invalid_time_window", "end must include a timezone.", status_code=422
        )
    start_utc = start.astimezone(UTC)
    end_utc = end.astimezone(UTC)
    if end_utc <= start_utc or (end_utc - start_utc) % PT15M:
        raise OrchestrationError(
            "invalid_time_window",
            "The window must contain complete PT15M intervals and end after start.",
            status_code=422,
        )
    return start_utc, end_utc


def residential_pc6_profile_id(pc6: str) -> str:
    return f"consumption-residential-electricity-pc6-demand-{pc6.lower()}-2023-pt15m"


def iso_z(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def same_instant(value: Any, expected: datetime) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return (
        parsed.tzinfo is not None
        and parsed.utcoffset() is not None
        and parsed.astimezone(UTC) == expected.astimezone(UTC)
    )


def load_pc6_geometry(path: Path, pc6: str) -> tuple[dict[str, Any], str]:
    try:
        stat = path.stat()
        catalog, artifact_sha256 = _load_pc6_catalog(
            str(path.resolve()), stat.st_mtime_ns, stat.st_size
        )
    except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
        raise OrchestrationError(
            "geometry_catalog_unavailable",
            "The PC6 geometry catalog is unavailable.",
            status_code=503,
        ) from exc
    geometry = catalog.get(pc6)
    if geometry is None:
        raise OrchestrationError(
            "pc6_not_found", f"PC6 {pc6} is not present in the geometry catalog.", status_code=404
        )
    return geometry, artifact_sha256


@lru_cache(maxsize=2)
def _load_pc6_catalog(
    resolved_path: str, mtime_ns: int, size: int
) -> tuple[dict[str, dict[str, Any]], str]:
    del mtime_ns, size
    raw = Path(resolved_path).read_bytes()
    document = json.loads(raw)
    features = document.get("features")
    if document.get("type") != "FeatureCollection" or not isinstance(features, list):
        raise ValueError("PC6 source must be a GeoJSON FeatureCollection")
    catalog: dict[str, dict[str, Any]] = {}
    for feature in features:
        if not isinstance(feature, dict):
            raise ValueError("PC6 feature must be an object")
        properties = feature.get("properties")
        geometry = feature.get("geometry")
        if not isinstance(properties, dict) or not isinstance(geometry, dict):
            raise ValueError("PC6 feature properties and geometry are required")
        code = properties.get("postcode6")
        if not isinstance(code, str) or not PC6_PATTERN.fullmatch(code):
            raise ValueError("PC6 feature has an invalid postcode6")
        if code in catalog:
            raise ValueError("PC6 geometry identifiers must be unique")
        catalog[code] = geometry
    return catalog, hashlib.sha256(raw).hexdigest()


def geometry_bbox(geometry: Mapping[str, Any]) -> list[float]:
    coordinates = geometry.get("coordinates")
    points = list(_coordinate_pairs(coordinates))
    if not points:
        raise OrchestrationError(
            "geometry_catalog_invalid",
            "The selected PC6 geometry has no coordinates.",
            status_code=503,
        )
    longitudes = [item[0] for item in points]
    latitudes = [item[1] for item in points]
    return [min(longitudes), min(latitudes), max(longitudes), max(latitudes)]


def _coordinate_pairs(value: Any):
    if (
        isinstance(value, list)
        and len(value) >= 2
        and isinstance(value[0], (int, float))
        and isinstance(value[1], (int, float))
    ):
        yield float(value[0]), float(value[1])
        return
    if isinstance(value, list):
        for child in value:
            yield from _coordinate_pairs(child)
