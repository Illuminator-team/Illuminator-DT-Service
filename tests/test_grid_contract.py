import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "layer-publisher"))

from grid import fetch_grid_artifact, load_grid_records  # noqa: E402
from pc6 import get_layer_config, load_manifest  # noqa: E402
from postgis_sql import multiline_values_template, point_values_template  # noqa: E402


RELEASE_COMMIT = "36bfcfbdca4030068a2ec1e2677bf2b334bb4a46"
CONTAINER_DIGEST = "sha256:ed241d2dc64de8f9cb21a56595f58725bac4cdf91932f5623d4e20b9867a83c2"
IMAGE_IDENTITY = f"ghcr.io/jortgroen/liander-grid-model-api@{CONTAINER_DIGEST}"
MODEL_VERSION = "1.0.0"
CONTRACT_VERSION = "1.0.0"
METHOD_VERSION = "1.0.0"
GRID_DATA_VERSION = "grid-acceptance-version"
BBOX = [4.774287, 52.629131, 4.779526, 52.635583]
RUN_ID = "11111111-1111-4111-8111-111111111111"
LINE_OUTPUT_ID = "22222222-2222-4222-8222-222222222222"
TRANSFORMER_OUTPUT_ID = "33333333-3333-4333-8333-333333333333"
TIMESTAMP = "2026-08-07T15:00:00+00:00"


def common_properties(component_id, component_type, output_id, voltage_level="lv"):
    return {
        "feature_id": component_id,
        "component_id": component_id,
        "persistent_uri": f"https://reformers01.ewi.tudelft.nl/id/grid-component/{component_id}",
        "component_type": component_type,
        "voltage_level": voltage_level,
        "nominal_voltage": 0.4,
        "nominal_voltage_unit": "kV",
        "model_id": "https://reformers01.ewi.tudelft.nl/id/model/liander-grid-topology",
        "model_version": MODEL_VERSION,
        "method_version": METHOD_VERSION,
        "grid_data_version": GRID_DATA_VERSION,
        "source_reference_period": None,
        "source_modified_at": None,
        "source_retrieved_at": TIMESTAMP,
        "source_last_updated": None,
        "cache_generated_at": TIMESTAMP,
        "datacompleetheid": 2,
        "datacompleetheid_label": "behoorlijk compleet",
        "datacompleetheid_rule_version": "datacompleetheid-grid-v1",
        "datacompleetheid_assessed_at": TIMESTAMP,
        "datacompleetheid_reason_codes": ["topology_contains_versioned_inference"],
        "datacompleetheid_summary": "Registered evidence with a documented topology assumption.",
        "run_id": RUN_ID,
        "output_id": output_id,
        "model_run_at": TIMESTAMP,
        "output_generated_at": TIMESTAMP,
    }


def line_feature(component_id="grid-line-acceptance"):
    properties = common_properties(
        component_id, "lv_cable", LINE_OUTPUT_ID
    )
    properties.update(
        {
            "model_component_name": "line_lv_acceptance",
            "length_km": 0.12,
            "in_service": True,
            "evidence_status": "registered",
            "connected_transformer_ids": ["grid-transformer-trafo_MV_LV_1157"],
            "serving_transformer_id": "grid-transformer-trafo_MV_LV_1157",
        }
    )
    return {
        "type": "Feature",
        "id": component_id,
        "properties": properties,
        "geometry": {
            "type": "LineString",
            "coordinates": [[4.775, 52.630], [4.776, 52.631]],
        },
    }


def transformer_feature():
    component_id = "grid-transformer-trafo_MV_LV_1157"
    properties = common_properties(
        component_id, "lv_mv_transformer", TRANSFORMER_OUTPUT_ID
    )
    properties.update(
        {
            "model_component_name": "trafo_MV_LV_1157",
            "transformer_type": "lv_mv",
            "primary_nominal_voltage_kv": 10.0,
            "secondary_nominal_voltage_kv": 0.4,
            "rated_power_kva": 630.0,
            "in_service": True,
            "source_station_objectid": None,
            "source_station_name": None,
        }
    )
    return {
        "type": "Feature",
        "id": component_id,
        "properties": properties,
        "geometry": {"type": "Point", "coordinates": [4.7755, 52.6305]},
    }


class FakeResponse:
    def __init__(self, *, document=None, content=None, content_type="application/json"):
        self._document = document
        self.content = content if content is not None else json.dumps(document).encode("utf-8")
        self.headers = {"content-type": content_type}

    def json(self):
        return copy.deepcopy(self._document)

    def raise_for_status(self):
        return None


class FakeSession:
    def __init__(self, *, data_link=None):
        collections = {
            "grid_lines": {"type": "FeatureCollection", "features": [line_feature()]},
            "grid_transformers": {
                "type": "FeatureCollection",
                "features": [transformer_feature()],
            },
        }
        output_ids = {
            "grid_lines": LINE_OUTPUT_ID,
            "grid_transformers": TRANSFORMER_OUTPUT_ID,
        }
        self.outputs = {}
        self.data = {}
        summaries = []
        for layer_id, collection in collections.items():
            output_id = output_ids[layer_id]
            content = json.dumps(collection, separators=(",", ":")).encode("utf-8")
            link = data_link if layer_id == "grid_lines" and data_link else f"/outputs/{output_id}/data"
            self.outputs[layer_id] = {
                "output_id": output_id,
                "run_id": RUN_ID,
                "layer_id": layer_id,
                "status": "available",
                "media_type": "application/geo+json",
                "feature_count": 1,
                "byte_size": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "generated_at": TIMESTAMP,
                "links": {"data": link},
            }
            self.data[layer_id] = FakeResponse(
                document=collection,
                content=content,
                content_type="application/geo+json",
            )
            summaries.append(
                {
                    "output_id": output_id,
                    "layer_id": layer_id,
                    "feature_count": 1,
                    "links": {
                        "self": f"/outputs/{output_id}",
                        "data": f"/outputs/{output_id}/data",
                        "run": f"/runs/{RUN_ID}",
                    },
                }
            )
        self.run = {
            "run_id": RUN_ID,
            "status": "completed",
            "outputs": summaries,
        }
        self.routes = {
            ("GET", "/ready"): FakeResponse(
                document={
                    "status": "ready",
                    "grid_data_version": GRID_DATA_VERSION,
                    "data_mode": "fixture",
                    "timestamp": TIMESTAMP,
                }
            ),
            ("GET", "/metadata"): FakeResponse(
                document={
                    "contract_version": CONTRACT_VERSION,
                    "model": {
                        "id": "https://reformers01.ewi.tudelft.nl/id/model/liander-grid-topology",
                        "version": MODEL_VERSION,
                    },
                    "method": {"version": METHOD_VERSION},
                    "release": {
                        "git_commit": RELEASE_COMMIT,
                        "container_digest": CONTAINER_DIGEST,
                    },
                    "active_grid_data": {
                        "grid_data_version": GRID_DATA_VERSION,
                        "data_mode": "fixture",
                    },
                }
            ),
            ("GET", "/layers"): FakeResponse(
                document={
                    "layers": [
                        {"id": layer_id, "runtime": {"feature_count": 1}}
                        for layer_id in ("grid_lines", "grid_transformers")
                    ]
                }
            ),
            ("POST", "/runs"): FakeResponse(document=self.run),
            ("GET", f"/runs/{RUN_ID}"): FakeResponse(document=self.run),
        }
        for layer_id, output in self.outputs.items():
            output_id = output_ids[layer_id]
            self.routes[("GET", f"/outputs/{output_id}")] = FakeResponse(document=output)
            self.routes[("GET", f"/outputs/{output_id}/data")] = self.data[layer_id]
        self.requests = []

    def request(self, method, url, **kwargs):
        path = urlparse(url).path
        self.requests.append((method, path, kwargs.get("json")))
        return self.routes[(method, path)]


class GridContractTest(unittest.TestCase):
    def test_manifest_pins_the_merged_grid_release(self):
        manifest = load_manifest(ROOT / "layer-publisher" / "layer-manifest.json")
        for local_id, table in (
            ("layer:grid-model:lines", "grid_lines"),
            ("layer:grid-model:transformers", "grid_transformers"),
        ):
            layer = get_layer_config(manifest, local_id)
            self.assertEqual(layer["table"], table)
            self.assertEqual(layer["source"]["release_commit"], RELEASE_COMMIT)
            self.assertEqual(layer["source"]["container_image"], IMAGE_IDENTITY)
            self.assertEqual(layer["source"]["container_digest"], CONTAINER_DIGEST)
            self.assertEqual(
                layer["data_quality"]["method_version"],
                "datacompleetheid-grid-v1",
            )

    def test_line_and_transformer_contracts_accept_model_owned_fields(self):
        lines = load_grid_records(
            {"type": "FeatureCollection", "features": [line_feature()]},
            layer_id="grid_lines",
            expected_model_version=MODEL_VERSION,
            expected_method_version=METHOD_VERSION,
            expected_grid_data_version=GRID_DATA_VERSION,
            expected_output_id=LINE_OUTPUT_ID,
        )
        transformers = load_grid_records(
            {"type": "FeatureCollection", "features": [transformer_feature()]},
            layer_id="grid_transformers",
            expected_model_version=MODEL_VERSION,
            expected_method_version=METHOD_VERSION,
            expected_grid_data_version=GRID_DATA_VERSION,
            expected_output_id=TRANSFORMER_OUTPUT_ID,
        )
        self.assertEqual(len(lines), 1)
        self.assertEqual(len(transformers), 1)
        self.assertEqual(lines[0].properties["voltage_level"], "lv")
        self.assertEqual(transformers[0].properties["rated_power_kva"], 630.0)
        self.assertEqual(len(lines[0].source_feature_hash), 64)

    def test_feature_hash_ignores_run_identity_but_detects_content_changes(self):
        first_feature = line_feature()
        first = load_grid_records(
            {"type": "FeatureCollection", "features": [first_feature]},
            layer_id="grid_lines",
            expected_model_version=MODEL_VERSION,
            expected_method_version=METHOD_VERSION,
            expected_grid_data_version=GRID_DATA_VERSION,
            expected_output_id=LINE_OUTPUT_ID,
        )[0]

        rerun_feature = copy.deepcopy(first_feature)
        rerun_output_id = "44444444-4444-4444-8444-444444444444"
        rerun_feature["properties"].update(
            {
                "run_id": "55555555-5555-4555-8555-555555555555",
                "output_id": rerun_output_id,
                "model_run_at": "2026-08-07T16:00:00+00:00",
                "output_generated_at": "2026-08-07T16:00:01+00:00",
            }
        )
        rerun = load_grid_records(
            {"type": "FeatureCollection", "features": [rerun_feature]},
            layer_id="grid_lines",
            expected_model_version=MODEL_VERSION,
            expected_method_version=METHOD_VERSION,
            expected_grid_data_version=GRID_DATA_VERSION,
            expected_output_id=rerun_output_id,
        )[0]
        self.assertEqual(first.source_feature_hash, rerun.source_feature_hash)

        rerun_feature["properties"]["length_km"] = 0.13
        changed = load_grid_records(
            {"type": "FeatureCollection", "features": [rerun_feature]},
            layer_id="grid_lines",
            expected_model_version=MODEL_VERSION,
            expected_method_version=METHOD_VERSION,
            expected_grid_data_version=GRID_DATA_VERSION,
            expected_output_id=rerun_output_id,
        )[0]
        self.assertNotEqual(first.source_feature_hash, changed.source_feature_hash)

    def test_contract_rejects_duplicate_component_ids(self):
        item = line_feature()
        with self.assertRaisesRegex(ValueError, "Duplicate grid component_id"):
            load_grid_records(
                {"type": "FeatureCollection", "features": [item, copy.deepcopy(item)]},
                layer_id="grid_lines",
                expected_model_version=MODEL_VERSION,
                expected_method_version=METHOD_VERSION,
                expected_grid_data_version=GRID_DATA_VERSION,
                expected_output_id=LINE_OUTPUT_ID,
            )

    def test_http_handoff_verifies_bounded_two_layer_artifact(self):
        session = FakeSession()
        artifact = fetch_grid_artifact(
            "http://grid-api:8080",
            bbox=BBOX,
            expected_release_commit=RELEASE_COMMIT,
            expected_container_digest=CONTAINER_DIGEST,
            expected_model_version=MODEL_VERSION,
            expected_contract_version=CONTRACT_VERSION,
            expected_data_mode="fixture",
            session=session,
        )
        self.assertEqual(set(artifact.records_by_layer), {"grid_lines", "grid_transformers"})
        post_request = next(item for item in session.requests if item[:2] == ("POST", "/runs"))
        self.assertEqual(post_request[2]["selection"]["bbox"], BBOX)
        self.assertEqual(
            post_request[2]["layer_ids"], ["grid_lines", "grid_transformers"]
        )

    def test_http_handoff_rejects_cross_origin_output_link(self):
        session = FakeSession(data_link="https://example.invalid/grid.geojson")
        with self.assertRaisesRegex(ValueError, "configured API origin"):
            fetch_grid_artifact(
                "http://grid-api:8080",
                bbox=BBOX,
                expected_release_commit=RELEASE_COMMIT,
                expected_container_digest=CONTAINER_DIGEST,
                expected_model_version=MODEL_VERSION,
                expected_contract_version=CONTRACT_VERSION,
                expected_data_mode="fixture",
                session=session,
            )

    def test_compose_uses_private_immutable_image_and_explicit_initializers(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        local = (ROOT / "docker-compose.local.yml").read_text(encoding="utf-8")
        self.assertIn(IMAGE_IDENTITY, compose)
        self.assertIn(RELEASE_COMMIT, compose)
        self.assertIn("--fetch-region", compose)
        self.assertIn("north-holland-towns", compose)
        self.assertIn("--allow-fixture", local)
        self.assertIn("GRID_EXPECTED_DATA_MODE: fixture", local)
        grid_service = compose.split("  grid-api:", 1)[1].split("#  ---", 1)[0]
        self.assertNotIn("GEOSERVER_ADMIN", grid_service)
        self.assertNotIn("POSTGRES_PASSWORD", grid_service)

    def test_acceptance_fixture_is_the_checked_model_fixture(self):
        fixture = ROOT / "tests" / "fixtures" / "grid" / "alkmaar_grid_fixture.json"
        payload = json.loads(fixture.read_text(encoding="utf-8"))
        self.assertEqual(payload["fixture_id"], "alkmaar-trafo-1157-v1")
        self.assertEqual(payload["provenance"]["expected_line_count"], 22)
        self.assertEqual(payload["provenance"]["selection"]["bbox"], BBOX)
        self.assertEqual(
            hashlib.sha256(fixture.read_bytes()).hexdigest(),
            "d16f6101ee6a58593b3cc3d4aca43eb0325737a4087d4b1ba450096426ff52a1",
        )

    def test_grid_geometry_sql_templates_are_balanced(self):
        for template in (multiline_values_template(2), point_values_template(2)):
            self.assertEqual(template.count("("), template.count(")"))
            self.assertEqual(template.count("%s"), 3)


if __name__ == "__main__":
    unittest.main()
