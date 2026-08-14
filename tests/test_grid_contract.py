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
from postgis_sql import (  # noqa: E402
    multiline_values_template,
    point_values_template,
    values_template,
)


RELEASE_COMMIT = "4059f6fbe066cc959ee7751779807b28ba1feae8"
CONTAINER_DIGEST = "sha256:72923720f25979326c7cd7f99fe65cef60866de0b47cc5fed14e01b96d876ec4"
IMAGE_IDENTITY = f"ghcr.io/jortgroen/liander-grid-model-api@{CONTAINER_DIGEST}"
MODEL_VERSION = "2.0.0"
CONTRACT_VERSION = "2.0.1"
METHOD_VERSION = "2.0.0"
GRID_DATA_VERSION = "grid-acceptance-version"
BBOX = [4.74454, 52.629131, 4.835248, 52.644642]
RUN_ID = "11111111-1111-4111-8111-111111111111"
LINE_OUTPUT_ID = "22222222-2222-4222-8222-222222222222"
TRANSFORMER_OUTPUT_ID = "33333333-3333-4333-8333-333333333333"
LV_MV_REACH_OUTPUT_ID = "44444444-4444-4444-8444-444444444444"
MV_HV_REACH_OUTPUT_ID = "55555555-5555-4555-8555-555555555555"
TIMESTAMP = "2026-08-08T07:00:00+00:00"


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

def reach_feature(level="lv_mv"):
    pc6_id = "1823AA"
    component_id = (
        f"grid-{level.replace('_', '-')}-transformer-reach-pc6-{pc6_id}"
    )
    output_id = (
        LV_MV_REACH_OUTPUT_ID if level == "lv_mv" else MV_HV_REACH_OUTPUT_ID
    )
    transformer_id = (
        "grid-transformer-trafo_MV_LV_1157"
        if level == "lv_mv"
        else "grid-transformer-mv-hv-station-alkmaar"
    )
    transformer_name = (
        "trafo_MV_LV_1157" if level == "lv_mv" else "OS Alkmaar"
    )
    properties = common_properties(
        component_id,
        f"{level}_transformer_reach",
        output_id,
        voltage_level="lv" if level == "lv_mv" else "mv",
    )
    properties.update(
        {
            "nominal_voltage": 0.4 if level == "lv_mv" else 10.0,
            "transformer_type": level,
            "pc6_id": pc6_id,
            "reach_level": level,
            "reach_method": (
                "pc6_lv_cable_length_share_v2"
                if level == "lv_mv"
                else "pc6_lv_cable_share_by_electrical_root_v2"
            ),
            "share_scope": "absolute_pc6_to_target",
            "dominant_transformer_id": transformer_id,
            "dominant_transformer_name": transformer_name,
            "dominant_transformer_share": 1.0,
            "dominant_transformer_share_percent": 100.0,
            "dominant_root_bus_id": "42",
            "runner_up_transformer_id": None,
            "runner_up_transformer_name": None,
            "runner_up_transformer_share": None,
            "runner_up_transformer_share_percent": None,
            "runner_up_root_bus_id": None,
            "share_margin": 1.0,
            "share_margin_percentage_points": 100.0,
            "entity_count": 1,
            "has_overlap": False,
            "is_ambiguous": False,
            "ambiguity_reason": None,
            "ranked_shares": [
                {
                    "rank": 1,
                    "transformer_id": transformer_id,
                    "transformer_name": transformer_name,
                    "target_type": (
                        "lv_mv_transformer"
                        if level == "lv_mv"
                        else "mv_hv_transformer_root"
                    ),
                    "share": 1.0,
                    "share_percent": 100.0,
                    "matched_lv_cable_length_m": 120.0,
                    "lv_mv_transformer_ids": [
                        "grid-transformer-trafo_MV_LV_1157"
                    ],
                    "mv_hv_transformer_ids": [
                        "grid-transformer-mv-hv-station-alkmaar"
                    ],
                    "root_bus_ids": ["42"],
                    "source_station_objectids": ["station-alkmaar"],
                    "match_methods": ["lv_cable_length_split"],
                }
            ],
            "matched_lv_cable_length_m": 120.0,
            "match_method": "lv_cable_length_split",
            "fallback_used": False,
            "fallback_bus_id": None,
            "fallback_distance_m": None,
            "match_evidence": {
                "pc6_source_id": "acceptance-pc6",
                "pc6_source_sha256": "a" * 64,
                "share_scope": "absolute_pc6_to_target",
                "match_methods": ["lv_cable_length_split"],
                "entry_bus_ids": ["101"],
                "matched_lv_cable_length_m": 120.0,
                "fallback_used": False,
                "fallback_bus_id": None,
                "fallback_distance_m": None,
            },
            "pc6_source_id": "acceptance-pc6",
            "pc6_source_sha256": "a" * 64,
            "evidence_status": "model_estimated",
        }
    )
    return {
        "type": "Feature",
        "id": component_id,
        "properties": properties,
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [4.775, 52.630], [4.778, 52.630], [4.778, 52.633],
                [4.775, 52.633], [4.775, 52.630],
            ]],
        },
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
            "grid_lv_mv_transformer_reach": {
                "type": "FeatureCollection",
                "features": [reach_feature("lv_mv")],
            },
            "grid_mv_hv_transformer_reach": {
                "type": "FeatureCollection",
                "features": [reach_feature("mv_hv")],
            },
        }
        output_ids = {
            "grid_lines": LINE_OUTPUT_ID,
            "grid_transformers": TRANSFORMER_OUTPUT_ID,
            "grid_lv_mv_transformer_reach": LV_MV_REACH_OUTPUT_ID,
            "grid_mv_hv_transformer_reach": MV_HV_REACH_OUTPUT_ID,
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
                        for layer_id in (
                            "grid_lines",
                            "grid_transformers",
                            "grid_lv_mv_transformer_reach",
                            "grid_mv_hv_transformer_reach",
                        )
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
            (
                "layer:grid-model:lv-mv-transformer-reach",
                "grid_lv_mv_transformer_reach",
            ),
            (
                "layer:grid-model:mv-hv-transformer-reach",
                "grid_mv_hv_transformer_reach",
            ),
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

    def test_grid_contracts_accept_model_owned_fields(self):
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
        lv_mv_reach = load_grid_records(
            {"type": "FeatureCollection", "features": [reach_feature("lv_mv")]},
            layer_id="grid_lv_mv_transformer_reach",
            expected_model_version=MODEL_VERSION,
            expected_method_version=METHOD_VERSION,
            expected_grid_data_version=GRID_DATA_VERSION,
            expected_output_id=LV_MV_REACH_OUTPUT_ID,
        )
        mv_hv_reach = load_grid_records(
            {"type": "FeatureCollection", "features": [reach_feature("mv_hv")]},
            layer_id="grid_mv_hv_transformer_reach",
            expected_model_version=MODEL_VERSION,
            expected_method_version=METHOD_VERSION,
            expected_grid_data_version=GRID_DATA_VERSION,
            expected_output_id=MV_HV_REACH_OUTPUT_ID,
        )
        self.assertEqual(len(lines), 1)
        self.assertEqual(len(transformers), 1)
        self.assertEqual(len(lv_mv_reach), 1)
        self.assertEqual(len(mv_hv_reach), 1)
        self.assertEqual(lines[0].properties["voltage_level"], "lv")
        self.assertEqual(transformers[0].properties["rated_power_kva"], 630.0)
        self.assertEqual(lv_mv_reach[0].properties["pc6_id"], "1823AA")
        self.assertEqual(
            mv_hv_reach[0].properties["dominant_transformer_name"],
            "OS Alkmaar",
        )
        self.assertEqual(len(mv_hv_reach[0].properties["ranked_shares"]), 1)
        self.assertEqual(
            mv_hv_reach[0].properties["share_scope"],
            "absolute_pc6_to_target",
        )
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
        rerun_output_id = "66666666-6666-4666-8666-666666666666"
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

    def test_http_handoff_verifies_bounded_four_layer_artifact(self):
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
        self.assertEqual(
            set(artifact.records_by_layer),
            {
                "grid_lines",
                "grid_transformers",
                "grid_lv_mv_transformer_reach",
                "grid_mv_hv_transformer_reach",
            },
        )
        post_request = next(item for item in session.requests if item[:2] == ("POST", "/runs"))
        self.assertEqual(post_request[2]["selection"]["bbox"], BBOX)
        self.assertEqual(
            post_request[2]["layer_ids"],
            [
                "grid_lines",
                "grid_transformers",
                "grid_lv_mv_transformer_reach",
                "grid_mv_hv_transformer_reach",
            ],
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
        ci = (ROOT / "docker-compose.ci.yml").read_text(encoding="utf-8")
        full_grid = (ROOT / "docker-compose.full-grid.yml").read_text(encoding="utf-8")
        self.assertIn(IMAGE_IDENTITY, compose)
        self.assertIn(RELEASE_COMMIT, compose)
        self.assertIn("--fetch-region", compose)
        self.assertIn("north-holland-towns", compose)
        self.assertNotIn("  grid-init:", local)
        self.assertNotIn("alkmaar_grid_fixture", local)
        self.assertNotIn("GRID_EXPECTED_DATA_MODE: fixture", local)
        self.assertIn("--allow-fixture", ci)
        self.assertIn("GRID_EXPECTED_DATA_MODE: fixture", ci)
        self.assertIn("GRID_EXPECTED_DATA_MODE: real_source", full_grid)
        self.assertIn("GRID_MODEL_DATA_VOLUME", full_grid)
        self.assertIn("external: true", full_grid)
        self.assertIn("GRID_EXPORT_BBOX: 4.60,52.50,4.98,52.88", compose)
        grid_service = compose.split("  grid-api:", 1)[1].split("#  ---", 1)[0]
        self.assertNotIn("GEOSERVER_ADMIN", grid_service)
        self.assertNotIn("POSTGRES_PASSWORD", grid_service)

    def test_acceptance_fixture_is_the_checked_model_fixture(self):
        fixture = ROOT / "tests" / "fixtures" / "grid" / "alkmaar_grid_fixture.json"
        payload = json.loads(fixture.read_text(encoding="utf-8"))
        self.assertEqual(payload["fixture_id"], "alkmaar-trafo-1157-pc6-reach-v3")
        self.assertEqual(payload["provenance"]["expected_line_count"], 34)
        self.assertEqual(len(payload["pc6"]["features"]), 2)
        self.assertEqual(payload["provenance"]["selection"]["bbox"], BBOX)
        self.assertEqual(
            hashlib.sha256(
                fixture.read_text(encoding="utf-8").encode("utf-8")
            ).hexdigest(),
            "4cf159559528c56ee43ccee79e2d851535761eee0d5aef9580b5204534ff3a12",
        )

    def test_grid_geometry_sql_templates_are_balanced(self):
        for template in (multiline_values_template(2), point_values_template(2), values_template(2)):
            self.assertEqual(template.count("("), template.count(")"))
            self.assertEqual(template.count("%s"), 3)


if __name__ == "__main__":
    unittest.main()
