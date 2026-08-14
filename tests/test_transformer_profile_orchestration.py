import copy
import hashlib
import json
import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "policy-tool-backend"))

from orchestration import (  # noqa: E402
    ModelApiClient,
    OrchestrationError,
    TransformerProfileOrchestrator,
    geometry_bbox,
    validate_request_timeout,
)


GRID_RUN_ID = "11111111-1111-4111-8111-111111111111"
GRID_OUTPUT_ID = "22222222-2222-4222-8222-222222222222"
CONGESTION_RUN_ID = "33333333-3333-4333-8333-333333333333"
CONGESTION_OUTPUT_ID = "44444444-4444-4444-8444-444444444444"
CONSUMPTION_RUN_ID = "run_55555555555545558555555555555555"
CONSUMPTION_OUTPUT_ID = "out_66666666666646668666666666666666"
CONSUMPTION_LAYER_VERSION = "7" * 64
CONSUMPTION_PROFILE_VERSION = "8" * 64
CONSUMPTION_RELEASE_COMMIT = "e5f44368b01bee9f4a77a409e6894f22f57f9684"
PV_RELEASE_COMMIT = "4c920c47c34075831a5ad49e9d8f45d9dfac2ae7"
PV_IMAGE = (
    "ghcr.io/jortgroen/pv-map-api@sha256:"
    "b1748568535499bbb58908fd9b677ddf2f33b3569fd8c76af25672bd612478e6"
)
PV_CAPACITY_OUTPUT_ID = "77777777777747778777777777777777"
PV_RUN_ID = "88888888888848888888888888888888"
PV_OUTPUT_ID = "99999999999949998999999999999999"
PV_PROFILE_ID = "pv_production_BU03610302_koersvaste_middenweg_2035"
PV_PROFILE_VERSION = "1.0.0+0123456789abcdef"
CONGESTION_IMAGE = (
    "ghcr.io/jortgroen/congestion-backend@sha256:"
    "d44df2b778508747fa2133740130fa97692a1198e5d91f0e14e0474f671eceea"
)
GRID_CROSSWALK_IMAGE = (
    "ghcr.io/jortgroen/liander-grid-crosswalk@sha256:"
    "f17e0a27f665a8885aa1f527359c22889ce5d2e3ead14dc4eb5d0e582154774e"
)
START = datetime(2022, 12, 31, 23, 0, tzinfo=UTC)
END = datetime(2023, 1, 1, 0, 0, tzinfo=UTC)
GEOMETRY = {
    "type": "Polygon",
    "coordinates": [[[4.85, 52.56], [4.86, 52.57], [4.85, 52.56]]],
}


class FakeResponse:
    def __init__(
        self,
        document=None,
        *,
        status_code=200,
        content=None,
        content_type="application/json",
    ):
        self.document = document
        self.status_code = status_code
        self.content = content
        self.headers = {"content-type": content_type}

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return copy.deepcopy(self.document)


class FakeSession:
    def __init__(self, routes):
        self.routes = routes
        self.requests = []

    def request(self, method, url, **kwargs):
        path = urlparse(url).path
        self.requests.append((method, path, copy.deepcopy(kwargs.get("json"))))
        response = self.routes[(method, path)]
        if isinstance(response, list):
            return response.pop(0)
        return response


def completed_run(run_id, output_id):
    return {
        "run_id": run_id,
        "status": "completed",
        "outputs": [{"output_id": output_id}],
    }


def output_routes(result, *, sha256=None):
    canonical = json.dumps(
        result,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        ("GET", f"/outputs/{CONGESTION_OUTPUT_ID}"): FakeResponse(
            {
                "output_id": CONGESTION_OUTPUT_ID,
                "media_type": "application/json",
                "byte_size": len(canonical),
                "sha256": sha256 or hashlib.sha256(canonical).hexdigest(),
            }
        ),
        ("GET", f"/outputs/{CONGESTION_OUTPUT_ID}/data"): FakeResponse(result),
    }


def consumption_routes(*, semantic_sha256=None):
    profile_id = (
        "consumption-residential-electricity-pc6-demand-1483aa-2023-pt15m"
    )
    document = {
        "metadata_contract_version": "reformers-consumption-v1",
        "model_id": "consumption-map",
        "model_version": "0.4.0",
        "dataset_id": "alkmaar_2023",
        "layer_id": "residential_electricity_pc6_profiles_pt15m",
        "layer_version": CONSUMPTION_LAYER_VERSION,
        "requested_period": {
            "start_inclusive": "2022-12-31T23:00:00+00:00",
            "end_exclusive": "2023-01-01T00:00:00+00:00",
            "resolution": "PT15M",
            "interval_semantics": "start_inclusive_end_exclusive",
            "interval_count": 4,
        },
        "interval_count_per_profile": 4,
        "profiles": [
            {
                "feature_id": "consumption-residential-electricity-pc6-1483aa",
                "spatial_unit_code": "1483AA",
                "profile_id": profile_id,
                "profile_version": CONSUMPTION_PROFILE_VERSION,
                "intervals": [
                    {"interval_start_utc": f"interval-{index}", "p_kw": 1.0}
                    for index in range(4)
                ],
            }
        ],
        "provenance": {
            "release_commit": CONSUMPTION_RELEASE_COMMIT,
            "profile_source_artifact_semantic_sha256": (
                CONSUMPTION_LAYER_VERSION
            ),
        },
    }
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
    return {
        ("POST", "/runs"): FakeResponse(
            {
                "run_id": CONSUMPTION_RUN_ID,
                "status": "succeeded",
                "output_ids": [CONSUMPTION_OUTPUT_ID],
            }
        ),
        ("GET", f"/outputs/{CONSUMPTION_OUTPUT_ID}"): FakeResponse(
            {
                "output_id": CONSUMPTION_OUTPUT_ID,
                "run_id": CONSUMPTION_RUN_ID,
                "status": "available",
                "layer_id": "residential_electricity_pc6_profiles_pt15m",
                "media_type": "application/json",
                "data_url": f"/outputs/{CONSUMPTION_OUTPUT_ID}/data",
                "profile_count": 1,
                "interval_count_per_profile": 4,
                "value_count": 4,
                "semantic_sha256": semantic_sha256
                or hashlib.sha256(canonical).hexdigest(),
            }
        ),
        ("GET", f"/outputs/{CONSUMPTION_OUTPUT_ID}/data"): FakeResponse(
            document
        ),
    }


def pv_routes(*, profile_sha256=None):
    start = "2024-06-01T00:00:00Z"
    end = "2024-06-01T01:00:00Z"
    capacity_document = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": "pv_capacity_BU03610302",
                "properties": {
                    "feature_id": "pv_capacity_BU03610302",
                    "source_feature_id": "BU03610302",
                    "cbs_buurt_code": "BU03610302",
                },
                "geometry": copy.deepcopy(GEOMETRY),
            }
        ],
    }
    capacity_bytes = json.dumps(
        capacity_document, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    profile_metadata = {
        "layer_id": "pv_production_profile",
        "profile_contract_version": "1.0.0",
        "contribution_kind": "production",
        "original_sign_convention": "positive_generation",
        "interval_duration": "PT15M",
        "interval_semantics": "start-inclusive/end-exclusive",
        "interval_count": 4,
        "scenario": "koersvaste_middenweg",
        "scenario_year": 2035,
        "profile_calendar": 2024,
        "profiles": [
            {
                "profile_id": PV_PROFILE_ID,
                "profile_version": PV_PROFILE_VERSION,
                "feature_id": "pv_capacity_BU03610302",
                "source_feature_id": "BU03610302",
            }
        ],
    }
    snapshot = {
        "metadata_contract_version": "2.1.0",
        "model": {"id": "pv-capacity-model", "version": "0.3.0"},
        "release": {
            "release_commit": PV_RELEASE_COMMIT,
            "container_image": PV_IMAGE,
            "model_version": "0.3.0",
            "metadata_contract_version": "2.1.0",
        },
        "production_profile": copy.deepcopy(profile_metadata),
    }
    request = {
        "output_type": "production_profile",
        "spatial_selection": {
            "type": "cbs_buurt",
            "feature_ids": ["BU03610302"],
        },
        "time_window": {"start": start, "end_exclusive": end},
        "scenario": "koersvaste_middenweg",
        "scenario_year": 2035,
        "profile_calendar": 2024,
        "parameters": {},
    }
    rows = [
        "profile_id,profile_version,feature_id,source_feature_id,interval_start_utc,pv_ac_generation_kw"
    ]
    for index, timestamp in enumerate(
        (
            "2024-06-01T00:00:00+0000",
            "2024-06-01T00:15:00+0000",
            "2024-06-01T00:30:00+0000",
            "2024-06-01T00:45:00+0000",
        )
    ):
        rows.append(
            f"{PV_PROFILE_ID},{PV_PROFILE_VERSION},pv_capacity_BU03610302,"
            f"BU03610302,{timestamp},{index + 1}.0"
        )
    profile_bytes = ("\n".join(rows) + "\n").encode("utf-8")
    profile_digest = profile_sha256 or hashlib.sha256(profile_bytes).hexdigest()
    capacity_path = f"/outputs/{PV_CAPACITY_OUTPUT_ID}"
    profile_path = f"/outputs/{PV_OUTPUT_ID}"
    return {
        ("GET", "/metadata"): FakeResponse(
            {
                "model_id": "pv-capacity-model",
                "model_version": "0.3.0",
                "metadata_contract_version": "2.1.0",
                "release_commit": PV_RELEASE_COMMIT,
                "container_image": PV_IMAGE,
                "production_profile": {
                    "layer_id": "pv_production_profile",
                    "profile_contract_version": "1.0.0",
                    "contribution_kind": "production",
                    "original_sign_convention": "positive_generation",
                    "interval_duration": "PT15M",
                    "scenario_year": 2035,
                    "profile_calendar": 2024,
                },
                "links": {"latest_output": capacity_path},
            }
        ),
        ("GET", capacity_path): FakeResponse(
            {
                "output_id": PV_CAPACITY_OUTPUT_ID,
                "output_type": "capacity",
                "layer_id": "pv_capacity",
                "media_type": "application/geo+json",
                "release_commit": PV_RELEASE_COMMIT,
                "container_image": PV_IMAGE,
                "model_version": "0.3.0",
                "byte_size": len(capacity_bytes),
                "sha256": hashlib.sha256(capacity_bytes).hexdigest(),
                "links": {"data": f"{capacity_path}/data"},
            }
        ),
        ("GET", f"{capacity_path}/data"): FakeResponse(
            content=capacity_bytes,
            content_type="application/geo+json",
        ),
        ("POST", "/runs"): FakeResponse(
            {
                "run_id": PV_RUN_ID,
                "status": "succeeded",
                "model_id": "pv-capacity-model",
                "model_version": "0.3.0",
                "metadata_contract_version": "2.1.0",
                "release_commit": PV_RELEASE_COMMIT,
                "container_image": PV_IMAGE,
                "metadata_snapshot": copy.deepcopy(snapshot),
                "input": request,
                "output_ids": [PV_OUTPUT_ID],
                "errors": [],
            },
            status_code=201,
        ),
        ("GET", profile_path): FakeResponse(
            {
                "output_id": PV_OUTPUT_ID,
                "run_id": PV_RUN_ID,
                "output_type": "production_profile",
                "layer_id": "pv_production_profile",
                "media_type": "text/csv",
                "output_format": "csv",
                "contribution_kind": "production",
                "unit": "kW",
                "model_version": "0.3.0",
                "metadata_contract_version": "2.1.0",
                "release_commit": PV_RELEASE_COMMIT,
                "container_image": PV_IMAGE,
                "feature_count": 1,
                "profile_count": 1,
                "interval_count": 4,
                "byte_size": len(profile_bytes),
                "sha256": profile_digest,
                "metadata_snapshot": snapshot,
                "profile_metadata": profile_metadata,
                "links": {"data": f"{profile_path}/data"},
            }
        ),
        ("GET", f"{profile_path}/data"): FakeResponse(
            content=profile_bytes,
            content_type="text/csv",
        ),
    }


class TransformerProfileOrchestrationTest(unittest.TestCase):
    def test_request_timeout_is_bounded_and_finite(self):
        self.assertEqual(validate_request_timeout("120"), 120.0)
        for invalid in (True, 0, -1, float("nan"), float("inf"), 601, "invalid"):
            with self.subTest(value=invalid):
                with self.assertRaises(ValueError):
                    validate_request_timeout(invalid)

    def setUp(self):
        self.geometry_path = (
            ROOT / "policy-tool-frontend" / "data" / "alkmaar_energy_map.geojson"
        )

    def test_calls_grid_then_two_stage_congestion_and_returns_both_stages(self):
        consumption_session = FakeSession(consumption_routes())
        grid_session = FakeSession(
            {
                ("POST", "/runs"): FakeResponse(
                    completed_run(GRID_RUN_ID, GRID_OUTPUT_ID)
                )
            }
        )
        aggregate = {
            "aggregation_mode": "two_stage_provisional_estimated",
            "overall_datacompleetheid": 1,
            "complete": True,
            "lv_mv_source_aggregation": {
                "targets": [{"target_id": "lv-mv-1", "datacompleetheid": 2}]
            },
            "lv_mv_to_mv_hv": {
                "targets": [{"target_id": "mv-hv-1", "datacompleetheid": 2}]
            },
        }
        congestion_routes = {
            ("POST", "/runs"): FakeResponse(
                completed_run(CONGESTION_RUN_ID, CONGESTION_OUTPUT_ID)
            ),
            **output_routes(aggregate),
        }
        congestion_session = FakeSession(congestion_routes)
        orchestrator = self._orchestrator(
            grid_session, congestion_session, consumption_session
        )

        response = orchestrator.aggregate_pc6("1483 aa", start=START, end=END)

        self.assertEqual(response["status"], "completed")
        self.assertEqual(response["feature"]["source_feature_id"], "1483AA")
        self.assertEqual(response["grid_assignment"]["output_id"], GRID_OUTPUT_ID)
        self.assertEqual(
            response["congestion_aggregation"]["output_id"], CONGESTION_OUTPUT_ID
        )
        self.assertEqual(response["result"], aggregate)

        grid_payload = grid_session.requests[0][2]
        self.assertEqual(grid_payload["operation"], "assign_feature_hierarchy")
        self.assertEqual(
            grid_payload["hierarchy_policy"], "nearest_electrical_root_v1"
        )
        self.assertEqual(
            grid_payload["selection"]["bbox"],
            geometry_bbox(grid_payload["features"][0]["geometry"]),
        )
        self.assertEqual(
            grid_payload["source"],
            {
                "source_model_id": "consumption-map",
                "source_model_version": "0.4.0",
                "source_layer_id": (
                    "residential_electricity_pc6_profiles_pt15m"
                ),
                "source_layer_version": CONSUMPTION_LAYER_VERSION,
                "source_release_id": CONSUMPTION_RELEASE_COMMIT,
                "source_artifact_sha256": CONSUMPTION_LAYER_VERSION,
            },
        )
        self.assertEqual(
            grid_payload["features"][0]["source_feature_version"],
            CONSUMPTION_PROFILE_VERSION,
        )

        self.assertEqual(consumption_session.requests[0][0:2], ("POST", "/runs"))
        self.assertEqual(
            consumption_session.requests[0][2]["selection"]["feature_ids"],
            ["consumption-residential-electricity-pc6-1483aa"],
        )

        congestion_payload = congestion_session.requests[0][2]
        self.assertEqual(
            congestion_payload["aggregation_mode"], "two_stage_authoritative"
        )
        self.assertEqual(
            congestion_payload["hierarchy_policy"], "nearest_electrical_root_v1"
        )
        self.assertEqual(
            congestion_payload["grid_assignment_output_id"], GRID_OUTPUT_ID
        )
        self.assertEqual(
            congestion_payload["profiles"][0]["profile_id"],
            "consumption-residential-electricity-pc6-demand-1483aa-2023-pt15m",
        )
        self.assertEqual(congestion_payload["profiles"][0]["start"], "2022-12-31T23:00:00Z")
        self.assertEqual(congestion_payload["profiles"][0]["end"], "2023-01-01T00:00:00Z")
        self.assertEqual(
            response["congestion_aggregation"]["aggregation_mode"],
            "two_stage_provisional_estimated",
        )
        self.assertEqual(
            response["congestion_aggregation"]["hierarchy_policy"],
            "nearest_electrical_root_v1",
        )

    def test_rejects_invalid_window_before_calling_upstreams(self):
        grid_session = FakeSession({})
        congestion_session = FakeSession({})
        orchestrator = self._orchestrator(grid_session, congestion_session)

        with self.assertRaisesRegex(OrchestrationError, "complete PT15M") as raised:
            orchestrator.aggregate_pc6(
                "1483AA",
                start=START,
                end=datetime(2022, 12, 31, 23, 10, tzinfo=UTC),
            )

        self.assertEqual(raised.exception.status_code, 422)
        self.assertEqual(grid_session.requests, [])
        self.assertEqual(congestion_session.requests, [])

    def test_stops_when_grid_reports_failure(self):
        grid_session = FakeSession(
            {
                ("POST", "/runs"): FakeResponse(
                    {"run_id": GRID_RUN_ID, "status": "failed", "outputs": []}
                )
            }
        )
        congestion_session = FakeSession({})

        with self.assertRaisesRegex(OrchestrationError, "grid could not complete"):
            self._orchestrator(grid_session, congestion_session).aggregate_pc6(
                "1483AA", start=START, end=END
            )

        self.assertEqual(congestion_session.requests, [])

    def test_times_out_async_shaped_upstream_run(self):
        submitted = {"run_id": GRID_RUN_ID, "status": "submitted", "outputs": []}
        running = {"run_id": GRID_RUN_ID, "status": "running", "outputs": []}
        grid_session = FakeSession(
            {
                ("POST", "/runs"): FakeResponse(submitted),
                ("GET", f"/runs/{GRID_RUN_ID}"): FakeResponse(running),
            }
        )
        grid_client = ModelApiClient(
            "http://grid-api:8080",
            "grid",
            session=grid_session,
            poll_attempts=1,
            sleeper=lambda _: None,
        )

        with self.assertRaisesRegex(OrchestrationError, "polling window") as raised:
            grid_client.create_completed_run({"operation": "test"})

        self.assertEqual(raised.exception.status_code, 504)

    def test_rejects_congestion_output_checksum_mismatch(self):
        grid_session = FakeSession(
            {
                ("POST", "/runs"): FakeResponse(
                    completed_run(GRID_RUN_ID, GRID_OUTPUT_ID)
                )
            }
        )
        aggregate = {"aggregation_mode": "two_stage_authoritative", "complete": True}
        congestion_session = FakeSession(
            {
                ("POST", "/runs"): FakeResponse(
                    completed_run(CONGESTION_RUN_ID, CONGESTION_OUTPUT_ID)
                ),
                **output_routes(aggregate, sha256="0" * 64),
            }
        )

        with self.assertRaisesRegex(OrchestrationError, "checksum"):
            self._orchestrator(grid_session, congestion_session).aggregate_pc6(
                "1483AA", start=START, end=END
            )

    def test_rejects_congestion_result_that_claims_authoritative_hierarchy(self):
        grid_session = FakeSession(
            {
                ("POST", "/runs"): FakeResponse(
                    completed_run(GRID_RUN_ID, GRID_OUTPUT_ID)
                )
            }
        )
        aggregate = {
            "aggregation_mode": "two_stage_authoritative",
            "overall_datacompleetheid": 1,
        }
        congestion_session = FakeSession(
            {
                ("POST", "/runs"): FakeResponse(
                    completed_run(CONGESTION_RUN_ID, CONGESTION_OUTPUT_ID)
                ),
                **output_routes(aggregate),
            }
        )

        with self.assertRaisesRegex(OrchestrationError, "authority mode"):
            self._orchestrator(grid_session, congestion_session).aggregate_pc6(
                "1483AA", start=START, end=END
            )

    def test_rejects_provisional_result_with_overstated_completeness(self):
        grid_session = FakeSession(
            {
                ("POST", "/runs"): FakeResponse(
                    completed_run(GRID_RUN_ID, GRID_OUTPUT_ID)
                )
            }
        )
        aggregate = {
            "aggregation_mode": "two_stage_provisional_estimated",
            "overall_datacompleetheid": 2,
        }
        congestion_session = FakeSession(
            {
                ("POST", "/runs"): FakeResponse(
                    completed_run(CONGESTION_RUN_ID, CONGESTION_OUTPUT_ID)
                ),
                **output_routes(aggregate),
            }
        )

        with self.assertRaisesRegex(OrchestrationError, "datacompleetheid"):
            self._orchestrator(grid_session, congestion_session).aggregate_pc6(
                "1483AA", start=START, end=END
            )

    def test_stops_before_grid_when_consumption_identity_drifts(self):
        consumption_session = FakeSession(
            consumption_routes(semantic_sha256="0" * 64)
        )
        grid_session = FakeSession({})

        with self.assertRaisesRegex(OrchestrationError, "checksum"):
            self._orchestrator(
                grid_session, FakeSession({}), consumption_session
            ).aggregate_pc6("1483AA", start=START, end=END)

        self.assertEqual(grid_session.requests, [])

    def test_stops_before_grid_when_consumption_window_drifts(self):
        routes = consumption_routes()
        output_path = f"/outputs/{CONSUMPTION_OUTPUT_ID}/data"
        document = routes[("GET", output_path)].document
        document["requested_period"]["end_exclusive"] = (
            "2023-01-01T00:15:00Z"
        )
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
        routes[("GET", f"/outputs/{CONSUMPTION_OUTPUT_ID}")].document[
            "semantic_sha256"
        ] = hashlib.sha256(canonical).hexdigest()
        grid_session = FakeSession({})

        with self.assertRaisesRegex(OrchestrationError, "time window"):
            self._orchestrator(
                grid_session, FakeSession({}), FakeSession(routes)
            ).aggregate_pc6("1483AA", start=START, end=END)

        self.assertEqual(grid_session.requests, [])

    def test_unknown_pc6_is_explicitly_not_found(self):
        orchestrator = self._orchestrator(FakeSession({}), FakeSession({}))

        with self.assertRaisesRegex(OrchestrationError, "not present") as raised:
            orchestrator.aggregate_pc6("9999ZZ", start=START, end=END)

        self.assertEqual(raised.exception.status_code, 404)

    def test_geometry_bbox_supports_nested_multipolygons(self):
        geometry = {
            "type": "MultiPolygon",
            "coordinates": [[GEOMETRY["coordinates"]], [[[4.8, 52.5], [4.9, 52.6]]]],
        }
        self.assertEqual(geometry_bbox(geometry), [4.8, 52.5, 4.9, 52.6])

    def test_aggregates_pv_buurt_through_grid_and_congestion(self):
        pv_session = FakeSession(pv_routes())
        grid_session = FakeSession(
            {
                ("POST", "/runs"): FakeResponse(
                    completed_run(GRID_RUN_ID, GRID_OUTPUT_ID)
                )
            }
        )
        aggregate = {
            "aggregation_mode": "two_stage_provisional_estimated",
            "overall_datacompleetheid": 1,
            "complete": True,
            "lv_mv_source_aggregation": {
                "targets": [
                    {
                        "target_id": "lv-mv-1",
                        "points": [
                            {"interval_start_utc": f"interval-{index}", "p_kw": -value}
                            for index, value in enumerate((1.0, 2.0, 3.0, 4.0))
                        ],
                    }
                ]
            },
            "lv_mv_to_mv_hv": {
                "targets": [
                    {
                        "target_id": "mv-hv-1",
                        "points": [
                            {"interval_start_utc": f"interval-{index}", "p_kw": -value}
                            for index, value in enumerate((1.0, 2.0, 3.0, 4.0))
                        ],
                    }
                ]
            },
        }
        congestion_session = FakeSession(
            {
                ("POST", "/runs"): FakeResponse(
                    completed_run(CONGESTION_RUN_ID, CONGESTION_OUTPUT_ID)
                ),
                **output_routes(aggregate),
            }
        )
        orchestrator = self._orchestrator(
            grid_session,
            congestion_session,
            pv_session=pv_session,
        )

        response = orchestrator.aggregate_pv_buurt(
            "bu03610302",
            start=datetime(2024, 6, 1, tzinfo=UTC),
            end=datetime(2024, 6, 1, 1, tzinfo=UTC),
        )

        self.assertEqual(response["status"], "completed")
        self.assertEqual(response["feature"]["source_feature_id"], "BU03610302")
        self.assertEqual(response["profile"]["profile_id"], PV_PROFILE_ID)
        self.assertEqual(response["profile"]["profile_calendar"], 2024)
        self.assertEqual(response["profile"]["scenario_year"], 2035)
        self.assertEqual(
            response["profile"]["canonical_sign_convention"],
            "negative_production",
        )

        grid_payload = grid_session.requests[0][2]
        self.assertEqual(grid_payload["hierarchy_policy"], "nearest_electrical_root_v1")
        self.assertEqual(
            grid_payload["source"],
            {
                "source_model_id": "pv-map",
                "source_model_version": "0.3.0",
                "source_layer_id": "pv_production_profile",
                "source_layer_version": "1.0.0",
                "source_release_id": PV_RELEASE_COMMIT,
                "source_artifact_sha256": hashlib.sha256(
                    pv_session.routes[("GET", f"/outputs/{PV_OUTPUT_ID}/data")].content
                ).hexdigest(),
            },
        )
        self.assertEqual(grid_payload["features"][0]["source_feature_type"], "cbs_buurt")
        self.assertEqual(
            grid_payload["features"][0]["source_feature_version"],
            PV_PROFILE_VERSION,
        )
        congestion_payload = congestion_session.requests[0][2]
        self.assertEqual(
            congestion_payload["profiles"],
            [
                {
                    "model_id": "pv-map",
                    "layer_id": "pv_production_profile",
                    "feature_type": "cbs_buurt",
                    "source_feature_id": "BU03610302",
                    "profile_id": PV_PROFILE_ID,
                    "start": "2024-06-01T00:00:00Z",
                    "end": "2024-06-01T01:00:00Z",
                }
            ],
        )
        self.assertEqual(
            [request[:2] for request in pv_session.requests],
            [
                ("GET", "/metadata"),
                ("GET", f"/outputs/{PV_CAPACITY_OUTPUT_ID}"),
                ("GET", f"/outputs/{PV_CAPACITY_OUTPUT_ID}/data"),
                ("POST", "/runs"),
                ("GET", f"/outputs/{PV_OUTPUT_ID}"),
                ("GET", f"/outputs/{PV_OUTPUT_ID}/data"),
            ],
        )

    def test_pv_rejects_non_2024_window_before_upstream_calls(self):
        pv_session = FakeSession({})
        grid_session = FakeSession({})
        orchestrator = self._orchestrator(
            grid_session,
            FakeSession({}),
            pv_session=pv_session,
        )

        with self.assertRaisesRegex(OrchestrationError, "2024") as raised:
            orchestrator.aggregate_pv_buurt(
                "BU03610302",
                start=datetime(2023, 6, 1, tzinfo=UTC),
                end=datetime(2023, 6, 1, 1, tzinfo=UTC),
            )

        self.assertEqual(raised.exception.status_code, 422)
        self.assertEqual(pv_session.requests, [])
        self.assertEqual(grid_session.requests, [])

    def test_pv_stops_before_grid_on_profile_checksum_mismatch(self):
        pv_session = FakeSession(pv_routes(profile_sha256="0" * 64))
        grid_session = FakeSession({})

        with self.assertRaisesRegex(OrchestrationError, "integrity"):
            self._orchestrator(
                grid_session,
                FakeSession({}),
                pv_session=pv_session,
            ).aggregate_pv_buurt(
                "BU03610302",
                start=datetime(2024, 6, 1, tzinfo=UTC),
                end=datetime(2024, 6, 1, 1, tzinfo=UTC),
            )

        self.assertEqual(grid_session.requests, [])

    def test_compose_wires_hardened_consumption_grid_congestion_flow(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        local = (ROOT / "docker-compose.local.yml").read_text(encoding="utf-8")
        ci = (ROOT / "docker-compose.ci.yml").read_text(encoding="utf-8")
        congestion = compose.split("  congestion-backend:", 1)[1].split(
            "  ##", 1
        )[0]
        policy = compose.split("  policy-tool-backend:", 1)[1].split(
            "  ##", 1
        )[0]

        self.assertIn(CONGESTION_IMAGE, compose)
        self.assertIn(GRID_CROSSWALK_IMAGE, compose)
        self.assertIn("CONGESTION_ADAPTER_MODE: http", congestion)
        self.assertIn("GRID_API_BASE_URL: http://grid-api:8080", congestion)
        self.assertIn(
            "CONSUMPTION_API_BASE_URL: http://consumption-api:8080",
            congestion,
        )
        self.assertIn("PV_API_BASE_URL: http://pv-api:8000", congestion)
        self.assertIn('PV_API_TIMEOUT_SECONDS: "120"', congestion)
        self.assertIn(f"PV_EXPECTED_RELEASE_COMMIT: {PV_RELEASE_COMMIT}", congestion)
        self.assertIn(f"PV_EXPECTED_CONTAINER_IMAGE: {PV_IMAGE}", congestion)
        self.assertIn("PV_EXPECTED_MODEL_VERSION: 0.3.0", congestion)
        self.assertNotIn("EV_API_BASE_URL", congestion)
        self.assertIn('user: "10001:10001"', congestion)
        self.assertIn("read_only: true", congestion)
        self.assertIn("no-new-privileges:true", congestion)
        self.assertIn("CONGESTION_API_URL=http://congestion-backend:8080", policy)
        self.assertIn("CONGESTION_REQUEST_TIMEOUT_SECONDS=120", policy)
        self.assertIn("CONSUMPTION_API_URL=http://consumption-api:8080", policy)
        self.assertIn("GRID_API_URL=http://grid-api:8080", policy)
        self.assertIn("PV_API_URL=http://pv-api:8000", policy)
        self.assertIn(
            f"PV_EXPECTED_RELEASE_COMMIT={PV_RELEASE_COMMIT}", policy
        )
        self.assertIn(f"PV_EXPECTED_CONTAINER_IMAGE={PV_IMAGE}", policy)
        self.assertIn("PV_EXPECTED_MODEL_VERSION=0.3.0", policy)
        self.assertIn("PV_REQUEST_TIMEOUT_SECONDS=120", policy)
        self.assertIn("alkmaar_energy_map.geojson:/app/config/", policy)
        self.assertIn("traefik.http.routers.congestion-api.rule", local)
        self.assertIn("orchestration-grid-init:", ci)
        self.assertIn("orchestration-grid-api:", ci)
        self.assertIn("orchestration_1483aa_bu03610709_grid_fixture.json", ci)
        self.assertIn("grid-crosswalk-data:/crosswalk:ro", ci)
        self.assertIn(
            "--buurt-pc6-crosswalk\n      - /crosswalk/alkmaar-buurt-pc6-2025.json",
            ci,
        )
        self.assertIn(
            "GRID_API_BASE_URL: http://orchestration-grid-api:8080",
            ci,
        )
        self.assertIn(
            "GRID_API_URL: http://orchestration-grid-api:8080",
            ci,
        )

    def _orchestrator(
        self,
        grid_session,
        congestion_session,
        consumption_session=None,
        pv_session=None,
    ):
        return TransformerProfileOrchestrator(
            consumption_client=ModelApiClient(
                "http://consumption-api:8080",
                "consumption",
                session=consumption_session or FakeSession(consumption_routes()),
            ),
            grid_client=ModelApiClient(
                "http://grid-api:8080", "grid", session=grid_session
            ),
            congestion_client=ModelApiClient(
                "http://congestion-backend:8080",
                "congestion",
                session=congestion_session,
            ),
            pc6_geometry_path=self.geometry_path,
            pv_client=ModelApiClient(
                "http://pv-api:8000",
                "pv",
                session=pv_session or FakeSession({}),
            ),
            pv_expected_release_commit=PV_RELEASE_COMMIT,
            pv_expected_container_image=PV_IMAGE,
            pv_expected_model_version="0.3.0",
        )


if __name__ == "__main__":
    unittest.main()
