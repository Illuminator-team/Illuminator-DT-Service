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


class TransformerProfileOrchestrationTest(unittest.TestCase):
    def setUp(self):
        self.geometry_path = (
            ROOT / "policy-tool-frontend" / "data" / "alkmaar_energy_map.geojson"
        )

    def test_calls_grid_then_two_stage_congestion_and_returns_both_stages(self):
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
        orchestrator = self._orchestrator(grid_session, congestion_session)

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
            len(grid_payload["source"]["source_artifact_sha256"]), 64
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

    def _orchestrator(self, grid_session, congestion_session):
        return TransformerProfileOrchestrator(
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
