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
CONGESTION_IMAGE = (
    "ghcr.io/jortgroen/congestion-backend@sha256:"
    "3f23bd186c4b719b4dda90d15f447c4825afff4bdf3013e23c524f45bf3926d1"
)
START = datetime(2022, 12, 31, 23, 0, tzinfo=UTC)
END = datetime(2023, 1, 1, 0, 0, tzinfo=UTC)
GEOMETRY = {
    "type": "Polygon",
    "coordinates": [[[4.85, 52.56], [4.86, 52.57], [4.85, 52.56]]],
}


class FakeResponse:
    def __init__(self, document, *, status_code=200):
        self.document = document
        self.status_code = status_code

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


class TransformerProfileOrchestrationTest(unittest.TestCase):
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
            "aggregation_mode": "two_stage_authoritative",
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
            congestion_payload["grid_assignment_output_id"], GRID_OUTPUT_ID
        )
        self.assertEqual(
            congestion_payload["profiles"][0]["profile_id"],
            "consumption-residential-electricity-pc6-demand-1483aa-2023-pt15m",
        )
        self.assertEqual(congestion_payload["profiles"][0]["start"], "2022-12-31T23:00:00Z")
        self.assertEqual(congestion_payload["profiles"][0]["end"], "2023-01-01T00:00:00Z")

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

    def test_compose_wires_hardened_consumption_grid_congestion_flow(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        local = (ROOT / "docker-compose.local.yml").read_text(encoding="utf-8")
        congestion = compose.split("  congestion-backend:", 1)[1].split(
            "  ##", 1
        )[0]
        policy = compose.split("  policy-tool-backend:", 1)[1].split(
            "  ##", 1
        )[0]

        self.assertIn(CONGESTION_IMAGE, compose)
        self.assertIn("CONGESTION_ADAPTER_MODE: http", congestion)
        self.assertIn("GRID_API_BASE_URL: http://grid-api:8080", congestion)
        self.assertIn(
            "CONSUMPTION_API_BASE_URL: http://consumption-api:8080",
            congestion,
        )
        self.assertNotIn("PV_API_BASE_URL", congestion)
        self.assertNotIn("EV_API_BASE_URL", congestion)
        self.assertIn('user: "10001:10001"', congestion)
        self.assertIn("read_only: true", congestion)
        self.assertIn("no-new-privileges:true", congestion)
        self.assertIn("CONGESTION_API_URL=http://congestion-backend:8080", policy)
        self.assertIn("CONSUMPTION_API_URL=http://consumption-api:8080", policy)
        self.assertIn("GRID_API_URL=http://grid-api:8080", policy)
        self.assertIn("alkmaar_energy_map.geojson:/app/config/", policy)
        self.assertIn("traefik.http.routers.congestion-api.rule", local)

    def _orchestrator(
        self, grid_session, congestion_session, consumption_session=None
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
        )


if __name__ == "__main__":
    unittest.main()
