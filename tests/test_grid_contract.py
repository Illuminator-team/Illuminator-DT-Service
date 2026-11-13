import copy
import hashlib
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch
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


RELEASE_COMMIT = "a08f5eade2a94ee0b82e6682632c704fb4740ac4"
CONTAINER_DIGEST = "sha256:7cab44fc8de4a764339490cb261af12dc2098c810dc6dc2a504786cc9dca98e0"
IMAGE_IDENTITY = f"ghcr.io/jortgroen/liander-grid-model-api@{CONTAINER_DIGEST}"
GRID_CROSSWALK_IMAGE = (
    "ghcr.io/jortgroen/liander-grid-crosswalk@sha256:"
    "f17e0a27f665a8885aa1f527359c22889ce5d2e3ead14dc4eb5d0e582154774e"
)
MODEL_VERSION = "2.7.0"
CONTRACT_VERSION = "2.9.0"
METHOD_VERSION = "2.7.0"
GRID_DATA_VERSION = "grid-acceptance-version"
BBOX = [4.74454, 52.629131, 4.835248, 52.644642]
RUN_ID = "11111111-1111-4111-8111-111111111111"
LINE_OUTPUT_ID = "22222222-2222-4222-8222-222222222222"
TRANSFORMER_OUTPUT_ID = "33333333-3333-4333-8333-333333333333"
LV_MV_REACH_OUTPUT_ID = "44444444-4444-4444-8444-444444444444"
MV_HV_REACH_OUTPUT_ID = "55555555-5555-4555-8555-555555555555"
CAPACITY_RUN_ID = "77777777-7777-4777-8777-777777777777"
CAPACITY_OUTPUT_ID = "88888888-8888-4888-8888-888888888888"
TIMESTAMP = "2026-08-08T07:00:00+00:00"


def load_grid_postgis_module():
    psycopg2 = types.ModuleType("psycopg2")
    psycopg2.connect = None
    extras = types.ModuleType("psycopg2.extras")
    extras.Json = object
    extras.execute_values = None
    spec = importlib.util.spec_from_file_location(
        "grid_postgis_under_test", ROOT / "layer-publisher" / "grid_postgis.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with patch.dict(
        sys.modules,
        {"psycopg2": psycopg2, "psycopg2.extras": extras},
    ):
        spec.loader.exec_module(module)
    return module


class SchemaCursor:
    def __init__(self, columns):
        self.columns = columns
        self.statements = []

    def execute(self, statement, parameters=None):
        self.statements.append((" ".join(statement.split()), parameters))

    def fetchall(self):
        return [(column,) for column in self.columns]


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
            "connected_mv_hv_transformer_ids": [
                "grid-transformer-mv-hv-station-alkmaar"
            ],
            "serving_mv_hv_transformer_id": (
                "grid-transformer-mv-hv-station-alkmaar"
            ),
            "root_bus_ids": ["42"],
            "source_station_objectids": ["station-alkmaar"],
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
            "upstream_mapping_status": "available",
            "upstream_mapping_method": (
                "electrical-connected-component-single-root-v1"
            ),
            "upstream_mv_hv_transformer_id": (
                "grid-transformer-mv-hv-station-alkmaar"
            ),
            "upstream_root_bus_id": "42",
            "upstream_source_station_objectid": "station-alkmaar",
            "upstream_candidate_root_bus_ids": ["42"],
            "upstream_candidate_mv_hv_transformer_ids": [
                "grid-transformer-mv-hv-station-alkmaar"
            ],
            "upstream_topology_path_edge_ids": ["line_1", "trafo_38"],
        }
    )
    return {
        "type": "Feature",
        "id": component_id,
        "properties": properties,
        "geometry": {"type": "Point", "coordinates": [4.7755, 52.6305]},
    }

def unavailable_reach_feature():
    """An MV/HV reach row for a PC6 whose station Grid cannot determine (model 2.7)."""
    feature = reach_feature("mv_hv")
    properties = feature["properties"]
    for field in (
        "dominant_transformer_id",
        "dominant_transformer_name",
        "dominant_transformer_share",
        "dominant_transformer_share_percent",
        "dominant_root_bus_id",
        "share_margin",
        "share_margin_percentage_points",
    ):
        properties[field] = None
    properties.update(
        assignment_status="unavailable",
        entity_count=0,
        ranked_shares=[],
        datacompleetheid=1,
        datacompleetheid_label="beperkt compleet",
        datacompleetheid_reason_codes=["topology_not_connected_to_known_source"],
    )
    return feature


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
            "assignment_status": "available",
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


def capacity_feature(pc6_id="1823AA", *, available=True):
    component_id = f"grid-capacity-limits-pc6-{pc6_id}"
    properties = common_properties(
        component_id, "capacity_limits", CAPACITY_OUTPUT_ID, voltage_level="mv"
    )
    area = "OS OUDORP 10-1i" if available else None
    properties.update(
        {
            "run_id": CAPACITY_RUN_ID,
            "nominal_voltage": 10.0,
            "source_reference_period": "2026",
            "datacompleetheid": 3 if available else 0,
            "datacompleetheid_rule_version": "datacompleetheid-grid-capacity-v1",
            "datacompleetheid_reason_codes": [
                "both_directions_resolved_to_published_service_area"
                if available
                else "no_registered_source_evidence"
            ],
            "pc6_id": pc6_id,
            "provider_id": "edsn",
            "source_id": "edsn-capaciteitskaart-open-data",
            "grid_operator_type": "RNB",
            "assignment_status": "available" if available else "unavailable",
            "rnb": "Liander" if available else None,
            "congestion_url": "https://www.liander.nl/" if available else None,
            "withdrawal_service_area_id": area,
            "withdrawal_service_area_name": area,
            "injection_service_area_id": area,
            "injection_service_area_name": area,
            "year_solved_withdrawal": "2033" if available else None,
            "year_solved_injection": "2033" if available else None,
            "tennet_year_solved_withdrawal": "2036" if available else None,
            "tennet_year_solved_injection": "2027" if available else None,
            "existing_transport_capacity_withdrawal_mw": 36.0 if available else None,
            "existing_transport_capacity_injection_mw": 36.0 if available else None,
            "required_transport_capacity_withdrawal_mw": 40.0 if available else None,
            "required_transport_capacity_injection_mw": 26.0 if available else None,
            "queue_withdrawal_mw": 29.8 if available else None,
            "queue_injection_mw": 12.5 if available else None,
            "unique_requests_withdrawal": 71 if available else None,
            "unique_requests_injection": 21 if available else None,
            "tennet_withdrawal_status_max": 3 if available else None,
            "tennet_injection_status_max": 3 if available else None,
        }
    )
    return {
        "type": "Feature",
        "id": component_id,
        "properties": properties,
        "geometry": {
            "type": "MultiPolygon",
            "coordinates": [[[[4.77, 52.63], [4.78, 52.63], [4.78, 52.64], [4.77, 52.63]]]],
        },
    }


def load_capacity(features):
    return load_grid_records(
        {"type": "FeatureCollection", "features": features},
        layer_id="grid_capacity_limits",
        expected_model_version=MODEL_VERSION,
        expected_method_version=METHOD_VERSION,
        expected_grid_data_version=GRID_DATA_VERSION,
        expected_output_id=CAPACITY_OUTPUT_ID,
    )


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
    def __init__(self, *, data_link=None, capacity=True):
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
        if capacity:
            collections["grid_capacity_limits"] = {
                "type": "FeatureCollection",
                "features": [capacity_feature()],
            }
            output_ids["grid_capacity_limits"] = CAPACITY_OUTPUT_ID
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
            run_id = CAPACITY_RUN_ID if layer_id == "grid_capacity_limits" else RUN_ID
            summaries.append(
                {
                    "output_id": output_id,
                    "layer_id": layer_id,
                    "feature_count": 1,
                    "links": {
                        "self": f"/outputs/{output_id}",
                        "data": f"/outputs/{output_id}/data",
                        "run": f"/runs/{run_id}",
                    },
                }
            )
        self.run = {
            "run_id": RUN_ID,
            "status": "completed",
            "outputs": [item for item in summaries if item["layer_id"] != "grid_capacity_limits"],
        }
        self.capacity_run = {
            "run_id": CAPACITY_RUN_ID,
            "status": "completed",
            "outputs": [item for item in summaries if item["layer_id"] == "grid_capacity_limits"],
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
                        for layer_id in collections
                    ]
                }
            ),
            ("GET", f"/runs/{RUN_ID}"): FakeResponse(document=self.run),
            ("GET", f"/runs/{CAPACITY_RUN_ID}"): FakeResponse(document=self.capacity_run),
        }
        for layer_id, output in self.outputs.items():
            output_id = output_ids[layer_id]
            self.routes[("GET", f"/outputs/{output_id}")] = FakeResponse(document=output)
            self.routes[("GET", f"/outputs/{output_id}/data")] = self.data[layer_id]
        self.requests = []

    def request(self, method, url, **kwargs):
        path = urlparse(url).path
        self.requests.append((method, path, kwargs.get("json")))
        if (method, path) == ("POST", "/runs"):
            if kwargs["json"]["layer_ids"] == ["grid_capacity_limits"]:
                return FakeResponse(document=self.capacity_run)
            return FakeResponse(document=self.run)
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

    def test_http_handoff_verifies_bounded_four_layer_artifact_and_capacity(self):
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
                "grid_capacity_limits",
            },
        )
        posts = [item for item in session.requests if item[:2] == ("POST", "/runs")]
        self.assertEqual(posts[0][2]["selection"]["bbox"], BBOX)
        self.assertEqual(
            [post[2]["layer_ids"] for post in posts],
            [
                [
                    "grid_lines",
                    "grid_transformers",
                    "grid_lv_mv_transformer_reach",
                    "grid_mv_hv_transformer_reach",
                ],
                ["grid_capacity_limits"],
            ],
        )
        self.assertEqual(artifact.output_ids["grid_capacity_limits"], CAPACITY_OUTPUT_ID)

    def handoff(self, session, **kwargs):
        return fetch_grid_artifact(
            "http://grid-api:8080",
            bbox=BBOX,
            expected_release_commit=RELEASE_COMMIT,
            expected_container_digest=CONTAINER_DIGEST,
            expected_model_version=MODEL_VERSION,
            expected_contract_version=CONTRACT_VERSION,
            expected_data_mode="fixture",
            session=session,
            **kwargs,
        )

    def test_capacity_layer_is_required_unless_disabled(self):
        with self.assertRaisesRegex(ValueError, "does not offer grid_capacity_limits"):
            self.handoff(FakeSession(capacity=False))
        session = FakeSession(capacity=False)
        artifact = self.handoff(session, require_capacity=False)
        self.assertNotIn("grid_capacity_limits", artifact.records_by_layer)
        self.assertEqual(
            len([item for item in session.requests if item[:2] == ("POST", "/runs")]), 1
        )
        # When the grid offers it, it is published even if not required.
        artifact = self.handoff(FakeSession(), require_capacity=False)
        self.assertIn("grid_capacity_limits", artifact.records_by_layer)

    def test_capacity_rows_keep_voedingsgebied_and_unavailable_pc6(self):
        records = load_capacity([capacity_feature("1823AA"), capacity_feature("1811AM", available=False)])
        available, unavailable = (record.properties for record in records)
        self.assertEqual(available["withdrawal_service_area_id"], "OS OUDORP 10-1i")
        self.assertEqual(available["existing_transport_capacity_withdrawal_mw"], 36.0)
        self.assertEqual(available["unique_requests_withdrawal"], 71)
        self.assertEqual(unavailable["assignment_status"], "unavailable")
        self.assertIsNone(unavailable["injection_service_area_id"])

    def load_mv_hv(self, feature):
        return load_grid_records(
            {"type": "FeatureCollection", "features": [feature]},
            layer_id="grid_mv_hv_transformer_reach",
            expected_model_version=MODEL_VERSION,
            expected_method_version=METHOD_VERSION,
            expected_grid_data_version=GRID_DATA_VERSION,
            expected_output_id=MV_HV_REACH_OUTPUT_ID,
        )

    def test_reach_rows_record_assignment_status(self):
        available = self.load_mv_hv(reach_feature("mv_hv"))[0].properties
        self.assertEqual(available["assignment_status"], "available")
        unavailable = self.load_mv_hv(unavailable_reach_feature())[0].properties
        self.assertEqual(unavailable["assignment_status"], "unavailable")
        self.assertIsNone(unavailable["dominant_transformer_id"])
        self.assertIsNone(unavailable["share_margin"])
        self.assertEqual(unavailable["entity_count"], 0)
        self.assertEqual(unavailable["ranked_shares"], [])
        self.assertEqual(unavailable["datacompleetheid"], 1)

    def test_unavailable_reach_rows_reject_drift(self):
        cases = {
            "unavailable transformer reach has dominant_transformer_id": lambda p: p.update(
                dominant_transformer_id="grid-transformer-mv-hv-station-alkmaar"
            ),
            "unavailable transformer reach has shares": lambda p: p.update(entity_count=1),
            "invalid transformer reach assignment_status": lambda p: p.update(
                assignment_status="partial"
            ),
        }
        for message, mutate in cases.items():
            with self.subTest(message=message):
                feature = unavailable_reach_feature()
                mutate(feature["properties"])
                with self.assertRaisesRegex(ValueError, message):
                    self.load_mv_hv(feature)

    def test_capacity_contract_rejects_drift(self):
        cases = {
            "no voedingsgebied": lambda p: p.update(withdrawal_service_area_id=None, injection_service_area_id=None),
            "unavailable capacity row has a voedingsgebied": lambda p: p.update(assignment_status="unavailable"),
            "capaciteitskaart source drift": lambda p: p.update(provider_id="other"),
            "PC6 capacity identity drift": lambda p: p.update(pc6_id="1823AB"),
            "datacompleetheid rule drift": lambda p: p.update(datacompleetheid_rule_version="datacompleetheid-grid-v1"),
            "must be finite and non-negative": lambda p: p.update(queue_withdrawal_mw=-1),
            "non-negative integer": lambda p: p.update(unique_requests_injection=1.5),
            "capacity assignment status drift": lambda p: p.update(assignment_status="partial"),
        }
        for message, mutate in cases.items():
            with self.subTest(message):
                feature = capacity_feature()
                mutate(feature["properties"])
                with self.assertRaisesRegex(ValueError, message):
                    load_capacity([feature])

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
        self.assertIn(GRID_CROSSWALK_IMAGE, compose)
        self.assertIn(RELEASE_COMMIT, compose)
        grid_init = compose.split("  grid-init:", 1)[1].split("  grid-capacity-refresh:", 1)[0]
        refresh = compose.split("  grid-capacity-refresh:", 1)[1].split("  grid-api:", 1)[0]
        # Liander's live service lacks the station attributes since 2026-11-08: build
        # from the retained snapshot, and never fetch EDSN while starting.
        self.assertNotIn("--fetch-region", grid_init)
        self.assertNotIn("--fetch-capaciteitskaart", grid_init)
        self.assertIn("--source-gpkg /data/sources/liander-north-holland-towns.gpkg", grid_init)
        self.assertIn("--source-retrieved-at 2026-08-18T09:53:06.188727+00:00", grid_init)
        self.assertIn("--capaciteitskaart-source-cache /data/sources/capaciteitskaart.json", grid_init)
        self.assertIn('profiles: ["maintenance"]', refresh)
        self.assertIn("--fetch-capaciteitskaart", refresh)
        self.assertIn("/data/sources/liander-north-holland-towns.gpkg", refresh)
        self.assertNotIn("  grid-init:", local)
        self.assertNotIn("alkmaar_grid_fixture", local)
        self.assertNotIn("GRID_EXPECTED_DATA_MODE: fixture", local)
        self.assertIn("--allow-fixture", ci)
        self.assertIn("GRID_EXPECTED_DATA_MODE: fixture", ci)
        self.assertIn("GRID_EXPECTED_DATA_MODE: real_source", full_grid)
        self.assertIn("GRID_MODEL_DATA_VOLUME", full_grid)
        self.assertIn("external: true", full_grid)
        self.assertIn("GRID_EXPORT_BBOX: 4.60,52.50,4.98,52.88", compose)
        self.assertIn("grid-crosswalk-init:", compose)
        self.assertIn("network_mode: none", compose)
        self.assertIn("grid-crosswalk-data:/crosswalk:ro", compose)
        self.assertIn("/crosswalk/alkmaar-cbs-postcode6-2024.geojson", compose)
        self.assertIn("/crosswalk/alkmaar-buurt-pc6-2025.json", compose)
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

    def test_orchestration_fixture_is_the_checked_combined_model_fixture(self):
        fixture = (
            ROOT
            / "tests"
            / "fixtures"
            / "grid"
            / "orchestration_1483aa_bu03610709_grid_fixture.json"
        )
        text = fixture.read_text(encoding="utf-8")
        payload = json.loads(text)
        provenance = payload["provenance"]

        self.assertEqual(
            payload["fixture_id"], "orchestration-1483aa-bu03610709-v1"
        )
        self.assertFalse(provenance["scientific_recomputation"])
        self.assertEqual(
            provenance["expected_counts"],
            {
                "buses": 341,
                "external_grids": 7,
                "lines": 156,
                "mv_hv_station_connections": 7,
                "pc6": 2,
                "switches": 180,
                "transformers": 6,
            },
        )
        self.assertEqual(
            set(provenance["expected_outcomes"]), {"1483AA", "BU03610709"}
        )
        for outcome in provenance["expected_outcomes"].values():
            self.assertAlmostEqual(sum(outcome["lv_mv_shares"].values()), 1.0, places=6)
        self.assertEqual(
            provenance["expected_outcomes"]["1483AA"]["mv_hv_root_bus_id"],
            "27999",
        )
        self.assertEqual(
            provenance["expected_outcomes"]["BU03610709"]["pc6_id"],
            "1831GD",
        )
        self.assertEqual(
            provenance["crosswalk_artifact_sha256"],
            "8824d7d4af024a40fb02cdf0762cf97cf1fb00d0bfe9cde8439c67581dba3651",
        )
        self.assertEqual(
            hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "778dbcc41216d2ec08400e2c4725564aebb3ff71864c5ad738354c5644cd9af8",
        )

    def test_grid_geometry_sql_templates_are_balanced(self):
        for template in (multiline_values_template(2), point_values_template(2), values_template(2)):
            self.assertEqual(template.count("("), template.count(")"))
            self.assertEqual(template.count("%s"), 3)

    def test_grid_table_is_recreated_when_lineage_columns_are_missing(self):
        grid_postgis = load_grid_postgis_module()
        required = set(grid_postgis.GRID_LAYER_SQL["grid_lines"]["fields"])
        old_columns = required - {
            "connected_mv_hv_transformer_ids",
            "serving_mv_hv_transformer_id",
            "root_bus_ids",
            "source_station_objectids",
        }
        old_cursor = SchemaCursor(old_columns)

        grid_postgis.create_grid_table(old_cursor, "grid_lines", "grid_lines")

        self.assertTrue(
            any(
                statement == "DROP TABLE public.grid_lines"
                for statement, _parameters in old_cursor.statements
            )
        )

        current_cursor = SchemaCursor(required)
        grid_postgis.create_grid_table(
            current_cursor, "grid_lines", "grid_lines"
        )
        self.assertFalse(
            any(
                statement.startswith("DROP TABLE")
                for statement, _parameters in current_cursor.statements
            )
        )


if __name__ == "__main__":
    unittest.main()
