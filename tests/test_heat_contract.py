import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "layer-publisher"))

from heat import (  # noqa: E402
    HEAT_LAYER_DEFINITIONS,
    HEAT_LAYER_IDS,
    fetch_heat_artifact,
    load_heat_layer_records,
)
from pc6 import get_layer_config, load_manifest  # noqa: E402

RELEASE_COMMIT = "1f2b2c8b770e5c59efbed4ab58641b40b164845a"
IMAGE_DIGEST = "sha256:2a1afe08732e98b00a880cad0ed3ffff2dbc8c38c960be4c643dd5358676dbda"
DEPLOYMENT_IMAGE = f"ghcr.io/jortgroen/heat-net-map-api@{IMAGE_DIGEST}"
MODEL_ID = "https://reformers01.ewi.tudelft.nl/id/model/heat-net-map"
MODEL_VERSION = "0.2.0"
CONTRACT_VERSION = "1.0.0"
SCHEMA_CONTRACT_VERSION = "1.0.0"
QUALITY_METHOD = "datacompleetheid-heat-net-v1"
RUN_ID = "11111111-1111-4111-8111-111111111111"
SNAPSHOT_ID = "22222222-2222-4222-8222-222222222222"
TIMESTAMP = "2026-08-14T10:07:19+02:00"
OUTPUT_IDS = {
    layer_id: f"{index:08d}-3333-4333-8333-333333333333"
    for index, layer_id in enumerate(HEAT_LAYER_IDS, start=1)
}


def _base_properties(layer_id, feature_id):
    return {
        "feature_id": feature_id,
        "persistent_uri": (
            f"https://reformers01.ewi.tudelft.nl/id/heat-net-map/"
            f"{layer_id}/{feature_id}"
        ),
        "layer_id": layer_id,
        "evidence_status": "documented_or_inferred_with_limitations",
        "datacompleetheid": 2,
        "datacompleetheid_label": "supported with limitations",
        "datacompleetheid_rule_version": QUALITY_METHOD,
        "fixture_only": True,
        "quality_evidence": {
            "reason_codes": ["documented_fixture_evidence"],
            "summary": "Supported with documented limitations.",
        },
        "provenance": {
            "model_id": MODEL_ID,
            "model_version": MODEL_VERSION,
            "method_id": "alkmaar-heat-network-evidence-v1",
            "method_version": "1.0.0",
            "scientific_model_run_at": None,
            "api_snapshot_published_at": TIMESTAMP,
            "api_run_id": RUN_ID,
            "api_output_id": OUTPUT_IDS[layer_id],
            "api_run_at": TIMESTAMP,
            "output_generated_at": TIMESTAMP,
            "sources": [{
                "source_id": "fixture-source",
                "publisher": "Fixture publisher",
                "reference_period": "2024",
                "retrieved_at": TIMESTAMP,
                "modified_at": None,
                "sha256": "a" * 64,
                "data_mode": "fixture",
            }],
        },
    }


def feature(layer_id):
    records = {
        "reported_neighbourhood_heat_consumers": (
            "neighbourhood-bu03610302",
            {
                "consumer_area_id": "BU03610302",
                "area_name": "FIXTURE Overdie-Oost",
                "reference_year": 2024,
                "reported_connected_share_pct": 44.0,
                "connected_dwellings_estimate": 44,
                "heat_demand_estimate_gj_per_year": 1012,
                "heat_demand_low_gj_per_year": 924,
                "heat_demand_high_gj_per_year": 1100,
            },
            {"type": "Polygon", "coordinates": [[[4.75, 52.62], [4.76, 52.62], [4.76, 52.63], [4.75, 52.62]]]},
        ),
        "inferred_pc6_heat_consumers": (
            "pc6-1812ab",
            {
                "postcode6": "1812AB",
                "allocated_connected_dwellings_est": 18,
                "heat_demand_gj_year_est": 414,
                "gas_avg_m3": 100,
                "electricity_avg_kwh": 2300,
                "inference_class": "strong_low_gas_normal_electricity",
                "corroboration": "reported_heat_neighbourhood",
                "liander_crosscheck_status": "supports_low_active_gas",
            },
            {"type": "Polygon", "coordinates": [[[4.752, 52.622], [4.755, 52.622], [4.755, 52.625], [4.752, 52.622]]]},
        ),
        "registered_heat_network_developments": (
            "development-9001",
            {
                "development_area_id": 9001,
                "development_name": "FIXTURE development area",
                "development_phase": "Fixture phase",
                "status_date": "2025-01-01T00:00:00Z",
                "planned_consumer_scale": "fixture 100",
                "planned_heat_source_description": "fixture source",
            },
            {"type": "Polygon", "coordinates": [[[4.77, 52.63], [4.78, 52.63], [4.78, 52.64], [4.77, 52.63]]]},
        ),
        "documented_actual_heat_sources": (
            "actual-source-fixture",
            {
                "source_name": "FIXTURE heat source",
                "source_status": "FIXTURE_NOT_REAL_SOURCE",
                "technology": "Fixture technology",
            },
            {"type": "Point", "coordinates": [4.761, 52.61]},
        ),
        "documented_large_heat_consumers": (
            "large-consumer-fixture",
            {
                "consumer_name": "FIXTURE large consumer",
                "connection_evidence": "Fixture documented example",
                "annual_heat_consumption": None,
            },
            {"type": "Point", "coordinates": [4.742, 52.613]},
        ),
        "potential_heat_sources": (
            "potential-source-fixture",
            {
                "source_name": "FIXTURE potential source",
                "source_type": "Fixture residual heat",
                "potential_thermal_capacity_mw": 0.5,
                "temperature_c": 30,
                "candidate_status": "FIXTURE_NOT_REAL_SOURCE",
            },
            {"type": "Point", "coordinates": [4.79, 52.64]},
        ),
    }
    feature_id, canonical, geometry = records[layer_id]
    properties = _base_properties(layer_id, feature_id)
    properties.update(canonical)
    return {
        "type": "Feature",
        "id": feature_id,
        "geometry": geometry,
        "properties": properties,
    }


def collection(layer_id):
    return {
        "type": "FeatureCollection",
        "features": [feature(layer_id)],
        "layer_id": layer_id,
        "crs_description": "OGC:CRS84; longitude, latitude; RFC 7946",
        "run_id": RUN_ID,
        "output_id": OUTPUT_IDS[layer_id],
        "generated_at": TIMESTAMP,
    }


class FakeResponse:
    def __init__(self, *, document=None, content=None, content_type="application/json"):
        self._document = document
        self.content = content if content is not None else json.dumps(document).encode()
        self.headers = {"content-type": content_type}

    def json(self):
        return copy.deepcopy(self._document)

    def raise_for_status(self):
        return None


class FakeSession:
    def __init__(self, *, cross_origin_layer=None):
        self.requests = []
        self.routes = {
            ("GET", "/ready"): FakeResponse(document={
                "status": "ready",
                "model_version": MODEL_VERSION,
                "snapshot_id": SNAPSHOT_ID,
                "data_mode": "fixture",
                "initialized_at": TIMESTAMP,
            }),
            ("GET", "/metadata"): FakeResponse(document={
                "contract_version": CONTRACT_VERSION,
                "schema_contract_version": SCHEMA_CONTRACT_VERSION,
                "model": {
                    "id": MODEL_ID,
                    "version": MODEL_VERSION,
                    "git_commit": RELEASE_COMMIT,
                },
                "crs": {"output": "OGC:CRS84"},
                "runtime": {"snapshot_id": SNAPSHOT_ID, "data_mode": "fixture"},
            }),
            ("GET", "/layers"): FakeResponse(document={
                "contract_version": CONTRACT_VERSION,
                "layers": [
                    {
                        "id": layer_id,
                        "geometry": sorted(definition["allowed_geometry"]),
                        "runtime": {
                            "snapshot_id": SNAPSHOT_ID,
                            "data_mode": "fixture",
                            "feature_count": 1,
                        },
                    }
                    for layer_id, definition in HEAT_LAYER_DEFINITIONS.items()
                ],
            }),
        }
        outputs = []
        for layer_id in HEAT_LAYER_IDS:
            output_id = OUTPUT_IDS[layer_id]
            payload = collection(layer_id)
            content = json.dumps(payload, separators=(",", ":")).encode()
            data_link = (
                "https://example.invalid/output.geojson"
                if layer_id == cross_origin_layer
                else f"/outputs/{output_id}/data"
            )
            output = {
                "output_id": output_id,
                "run_id": RUN_ID,
                "layer_id": layer_id,
                "status": "available",
                "media_type": "application/geo+json",
                "feature_count": 1,
                "byte_size": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "generated_at": TIMESTAMP,
                "metadata_snapshot": {
                    "model_id": MODEL_ID,
                    "model_version": MODEL_VERSION,
                    "contract_version": CONTRACT_VERSION,
                    "snapshot_id": SNAPSHOT_ID,
                    "data_mode": "fixture",
                },
                "links": {"data": data_link},
            }
            outputs.append({"output_id": output_id, "layer_id": layer_id, "feature_count": 1})
            self.routes[("GET", f"/outputs/{output_id}")] = FakeResponse(document=output)
            self.routes[("GET", f"/outputs/{output_id}/data")] = FakeResponse(
                document=payload,
                content=content,
                content_type="application/geo+json",
            )
        self.run = {"run_id": RUN_ID, "status": "completed", "outputs": outputs}
        self.routes[("POST", "/runs")] = FakeResponse(document=self.run)
        self.routes[("GET", f"/runs/{RUN_ID}")] = FakeResponse(document=self.run)

    def request(self, method, url, **kwargs):
        path = urlparse(url).path
        self.requests.append((method, path, kwargs.get("json")))
        return self.routes[(method, path)]


class HeatContractTest(unittest.TestCase):
    def test_manifest_pins_all_six_layers_to_one_private_release(self):
        manifest = load_manifest(ROOT / "layer-publisher" / "layer-manifest.json")
        for layer_id in HEAT_LAYER_IDS:
            layer = get_layer_config(manifest, f"layer:heat-net-map:{layer_id}")
            self.assertEqual(layer["source"]["model_layer_id"], layer_id)
            self.assertEqual(layer["source"]["release_commit"], RELEASE_COMMIT)
            self.assertEqual(layer["source"]["container_image"], DEPLOYMENT_IMAGE)
            self.assertEqual(layer["source"]["container_digest"], IMAGE_DIGEST)
            self.assertEqual(layer["data_quality"]["method_version"], QUALITY_METHOD)

    def test_all_six_fixture_layers_match_the_common_and_canonical_contracts(self):
        for layer_id in HEAT_LAYER_IDS:
            records = load_heat_layer_records(
                collection(layer_id),
                layer_id=layer_id,
                expected_run_id=RUN_ID,
                expected_output_id=OUTPUT_IDS[layer_id],
                expected_model_version=MODEL_VERSION,
                expected_data_mode="fixture",
            )
            self.assertEqual(len(records), 1)
            self.assertEqual(len(records[0].source_feature_hash), 64)
        pc6 = load_heat_layer_records(
            collection("inferred_pc6_heat_consumers"),
            layer_id="inferred_pc6_heat_consumers",
            expected_run_id=RUN_ID,
            expected_output_id=OUTPUT_IDS["inferred_pc6_heat_consumers"],
            expected_model_version=MODEL_VERSION,
            expected_data_mode="fixture",
        )[0]
        self.assertEqual(pc6.feature_id, "pc6-1812ab")
        self.assertEqual(pc6.canonical["allocated_connected_dwellings_est"], 18)
        self.assertEqual(pc6.canonical["heat_demand_gj_year_est"], 414)

    def test_content_hash_ignores_only_per_run_provenance(self):
        layer_id = "inferred_pc6_heat_consumers"
        first = collection(layer_id)
        second = copy.deepcopy(first)
        provenance = second["features"][0]["properties"]["provenance"]
        provenance.update({
            "api_run_at": "2026-08-14T10:08:19+02:00",
            "output_generated_at": "2026-08-14T10:08:20+02:00",
        })

        def record(payload):
            return load_heat_layer_records(
                payload,
                layer_id=layer_id,
                expected_run_id=RUN_ID,
                expected_output_id=OUTPUT_IDS[layer_id],
                expected_model_version=MODEL_VERSION,
                expected_data_mode="fixture",
            )[0]

        self.assertEqual(record(first).source_feature_hash, record(second).source_feature_hash)
        second["features"][0]["properties"]["heat_demand_gj_year_est"] += 1
        self.assertNotEqual(record(first).source_feature_hash, record(second).source_feature_hash)

    def test_http_handoff_returns_all_six_verified_outputs(self):
        session = FakeSession()
        artifact = fetch_heat_artifact(
            "http://heat-api:8080",
            expected_release_commit=RELEASE_COMMIT,
            expected_container_digest=IMAGE_DIGEST,
            expected_model_version=MODEL_VERSION,
            expected_contract_version=CONTRACT_VERSION,
            expected_schema_contract_version=SCHEMA_CONTRACT_VERSION,
            expected_data_mode="fixture",
            session=session,
        )
        self.assertEqual(set(artifact.layers), set(HEAT_LAYER_IDS))
        self.assertEqual(artifact.container_digest, IMAGE_DIGEST)
        self.assertIn((
            "POST",
            "/runs",
            {"layer_ids": list(HEAT_LAYER_IDS), "selection": {"type": "all"}},
        ), session.requests)

    def test_http_handoff_rejects_cross_origin_output_link(self):
        session = FakeSession(cross_origin_layer="potential_heat_sources")
        with self.assertRaisesRegex(ValueError, "configured API origin"):
            fetch_heat_artifact(
                "http://heat-api:8080",
                expected_release_commit=RELEASE_COMMIT,
                expected_container_digest=IMAGE_DIGEST,
                expected_model_version=MODEL_VERSION,
                expected_contract_version=CONTRACT_VERSION,
                expected_schema_contract_version=SCHEMA_CONTRACT_VERSION,
                expected_data_mode="fixture",
                session=session,
            )

    def test_compose_uses_digest_pin_hardening_and_explicit_fixture_mode(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        local = (ROOT / "docker-compose.local.yml").read_text(encoding="utf-8")
        heat_init = compose.split("  heat-init:", 1)[1].split("  heat-api:", 1)[0]
        heat_api = compose.split("  heat-api:", 1)[1].split("#  --", 1)[0]
        self.assertIn(DEPLOYMENT_IMAGE, compose)
        self.assertIn(RELEASE_COMMIT, compose)
        self.assertIn("real_source", heat_init)
        self.assertIn("--run-model", heat_init)
        self.assertIn('user: "10001:10001"', heat_init)
        self.assertIn("read_only: true", heat_init)
        self.assertIn("no-new-privileges:true", heat_init)
        self.assertIn("service_completed_successfully", heat_api)
        self.assertNotIn("GEOSERVER_ADMIN", heat_api)
        self.assertNotIn("POSTGRES_PASSWORD", heat_api)
        self.assertIn("--allow-fixture", local)
        self.assertIn("HEAT_EXPECTED_DATA_MODE: fixture", local)

    def test_publisher_image_contains_the_heat_modules(self):
        dockerfile = (ROOT / "layer-publisher" / "Dockerfile").read_text()
        self.assertIn("heat.py", dockerfile)
        self.assertIn("heat_postgis.py", dockerfile)


if __name__ == "__main__":
    unittest.main()
