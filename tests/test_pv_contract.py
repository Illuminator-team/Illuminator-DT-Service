import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "layer-publisher"))

from pc6 import get_layer_config, load_manifest  # noqa: E402
from pv import fetch_pv_artifact, load_pv_records  # noqa: E402

RELEASE_COMMIT = "bd29351e108d9db002b9e54d5c7fb2356416a306"
IMAGE_IDENTITY = "ghcr.io/jortgroen/pv-map-api@sha256:0fffb8dd6e725956257c4dc51c94225ea7c5745478ed33cf8bce597ee8551710"
CACHE_IMAGE_IDENTITY = "ghcr.io/jortgroen/pv-map-source-cache@sha256:e432f76ad7b6dfd67bb55c52445d985027c3a87f3de6e5502bedb1c236c8620b"
QUALITY_METHOD = "pv-datacompleetheid/1.0.0"
MODEL_VERSION = "0.3.0"
METADATA_CONTRACT_VERSION = "2.1.0"
RUN_ID = "run_test"
OUTPUT_ID = "output_test"


def feature(capacity=42.5):
    timestamp = "2026-08-05T09:00:00+00:00"
    return {
        "type": "Feature",
        "properties": {
            "feature_id": "pv_capacity_BU03610302",
            "feature_uri": "https://reformers01.ewi.tudelft.nl/id/pv_capacity_BU03610302",
            "source_feature_id": "BU03610302",
            "cbs_buurt_code": "BU03610302",
            "buurt_name": "Overdie-Oost",
            "municipality": "Alkmaar",
            "pv_capacity_kwp": capacity,
            "pv_capacity_mwp": capacity / 1000,
            "residential_kwp_real": 30.0,
            "commercial_kwp_derived": 12.5,
            "capacity_kwp_combined": capacity,
            "capacity_method": "model_estimated",
            "unit": "kWp",
            "residential_input_status": "observed",
            "datacompleetheid": 2,
            "datacompleetheid_label": "quite accurate",
            "datacompleetheid_method_version": QUALITY_METHOD,
            "datacompleetheid_assessed_at": timestamp,
            "datacompleetheid_observed": "CBS residential value",
            "datacompleetheid_estimated": "Spatial rescaling",
            "datacompleetheid_assumed": "Roof-area allocation",
            "datacompleetheid_missing": "none",
            "completeness_reason": "Observed inputs with model allocation.",
            "source_name": "CBS, PDOK and 3DBAG",
            "source_reference_period": "2022 and latest usable totals",
            "source_modified_at": None,
            "source_retrieved_at": timestamp,
            "source_last_updated": None,
            "model_run_at": timestamp,
            "output_generated_at": timestamp,
            "last_updated": timestamp,
            "model_version": "0.3.0",
            "metadata_contract_version": "2.1.0",
        },
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[4.70, 52.60], [4.71, 52.60], [4.71, 52.61], [4.70, 52.60]]],
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
        collection = {"type": "FeatureCollection", "features": [feature()]}
        artifact = json.dumps(collection, separators=(",", ":")).encode("utf-8")
        identity = {
            "release_commit": RELEASE_COMMIT,
            "container_image": IMAGE_IDENTITY,
        }
        self.run = {
            "run_id": RUN_ID,
            "status": "succeeded",
            "output_ids": [OUTPUT_ID],
            **identity,
        }
        self.output = {
            "output_id": OUTPUT_ID,
            "layer_id": "pv_capacity",
            "feature_count": 1,
            "media_type": "application/geo+json",
            "byte_size": len(artifact),
            "sha256": hashlib.sha256(artifact).hexdigest(),
            "output_generated_at": "2026-08-05T09:00:00+00:00",
            "datacompleetheid_method_version": QUALITY_METHOD,
            "links": {"data": data_link or f"/outputs/{OUTPUT_ID}/data"},
            "model_version": MODEL_VERSION,
            "metadata_contract_version": METADATA_CONTRACT_VERSION,
            **identity,
        }
        self.routes = {
            ("GET", "/ready"): FakeResponse(document={
                "ready": True,
                "state": "ready",
                "cache_inventory_fingerprint": "a" * 64,
                "finished_at": "2026-08-05T08:00:00+00:00",
            }),
            ("GET", "/metadata"): FakeResponse(document={
                "capacity_method": "model_estimated",
                "model_version": MODEL_VERSION,
                "metadata_contract_version": METADATA_CONTRACT_VERSION,
                **identity,
            }),
            ("GET", "/layers"): FakeResponse(document={"layers": [{
                "layer_id": "pv_capacity",
                "crs": "EPSG:4326",
                "datacompleetheid": {"method_version": QUALITY_METHOD},
                "model_version": MODEL_VERSION,
                "metadata_contract_version": METADATA_CONTRACT_VERSION,
                "attributes": [{"name": "pv_capacity_kwp", "unit": "kWp"}],
            }]}),
            ("POST", "/runs"): FakeResponse(document=self.run),
            ("GET", f"/runs/{RUN_ID}"): FakeResponse(document=self.run),
            ("GET", f"/outputs/{OUTPUT_ID}"): FakeResponse(document=self.output),
            ("GET", f"/outputs/{OUTPUT_ID}/data"): FakeResponse(
                document=collection,
                content=artifact,
                content_type="application/geo+json",
            ),
        }
        self.requests = []

    def request(self, method, url, **kwargs):
        path = urlparse(url).path
        self.requests.append((method, path, kwargs.get("json")))
        return self.routes[(method, path)]


class PvContractTest(unittest.TestCase):
    def test_publisher_manifest_pins_the_merged_model_release(self):
        manifest = load_manifest(ROOT / "layer-publisher" / "layer-manifest.json")
        layer = get_layer_config(manifest, "layer:pv-map:capacity")
        self.assertEqual(layer["table"], "pv_capacity")
        self.assertEqual(layer["geoserver_layer"], "pv_capacity")
        self.assertEqual(layer["source"]["release_commit"], RELEASE_COMMIT)
        self.assertEqual(layer["source"]["container_image"], IMAGE_IDENTITY)
        self.assertEqual(layer["source"]["crs"], "EPSG:4326")
        self.assertEqual(layer["data_quality"]["method_version"], QUALITY_METHOD)
        self.assertEqual(layer["style"]["style_status"], "default_geoserver")

    def test_geojson_contract_accepts_the_stable_overdie_fixture(self):
        records = load_pv_records(
            {"type": "FeatureCollection", "features": [feature()]},
            expected_quality_method_version=QUALITY_METHOD,
            expected_model_version=MODEL_VERSION,
            expected_metadata_contract_version=METADATA_CONTRACT_VERSION,
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].cbs_buurt_code, "BU03610302")
        self.assertGreater(records[0].properties["pv_capacity_kwp"], 0)
        self.assertEqual(len(records[0].source_feature_hash), 64)

    def test_geojson_contract_allows_empty_optional_evidence_categories(self):
        item = feature()
        item["properties"].update({
            "datacompleetheid_observed": "",
            "datacompleetheid_estimated": "",
            "datacompleetheid_assumed": "",
        })
        records = load_pv_records(
            {"type": "FeatureCollection", "features": [item]},
            expected_quality_method_version=QUALITY_METHOD,
            expected_model_version=MODEL_VERSION,
            expected_metadata_contract_version=METADATA_CONTRACT_VERSION,
        )
        self.assertEqual(len(records), 1)

    def test_geojson_contract_rejects_negative_capacity(self):
        with self.assertRaisesRegex(ValueError, "finite and non-negative"):
            load_pv_records(
                {"type": "FeatureCollection", "features": [feature(-1)]},
                expected_quality_method_version=QUALITY_METHOD,
                expected_model_version=MODEL_VERSION,
                expected_metadata_contract_version=METADATA_CONTRACT_VERSION,
            )

    def test_http_handoff_verifies_and_returns_exact_artifact(self):
        session = FakeSession()
        artifact = fetch_pv_artifact(
            "http://pv-api:8000",
            expected_release_commit=RELEASE_COMMIT,
            expected_container_image=IMAGE_IDENTITY,
            expected_model_version=MODEL_VERSION,
            expected_metadata_contract_version=METADATA_CONTRACT_VERSION,
            session=session,
        )
        self.assertEqual(len(artifact.records), 1)
        self.assertEqual(artifact.output_id, OUTPUT_ID)
        self.assertIn(
            (
                "POST",
                "/runs",
                {"spatial_selection": {"type": "all"}, "parameters": {}},
            ),
            session.requests,
        )

    def test_http_handoff_rejects_cross_origin_output_link(self):
        session = FakeSession(data_link="https://example.invalid/output.geojson")
        with self.assertRaisesRegex(ValueError, "configured API origin"):
            fetch_pv_artifact(
                "http://pv-api:8000",
                expected_release_commit=RELEASE_COMMIT,
                expected_container_image=IMAGE_IDENTITY,
                expected_model_version=MODEL_VERSION,
                expected_metadata_contract_version=METADATA_CONTRACT_VERSION,
                session=session,
            )

    def test_compose_keeps_shared_credentials_out_of_the_model(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        init_service = compose.split("  pv-init:", 1)[1].split("  pv-api:", 1)[0]
        pv_service = compose.split("  pv-api:", 1)[1].split("  ##", 1)[0]
        self.assertNotIn("GEOSERVER_ADMIN", pv_service)
        self.assertNotIn("POSTGRES_PASSWORD", pv_service)
        self.assertNotIn("PV-MAP.git", compose)
        self.assertIn(IMAGE_IDENTITY, compose)
        self.assertIn(CACHE_IMAGE_IDENTITY, compose)
        self.assertIn("PV_IMAGE_IDENTITY", pv_service)
        self.assertIn(RELEASE_COMMIT, compose)
        self.assertIn("service_completed_successfully", pv_service)
        self.assertIn("<<: *pv-cache-image", init_service)
        self.assertNotIn("command:", init_service)
        self.assertNotIn("PV_MODEL_CONFIG_PATH", init_service)
        self.assertNotIn("GEOSERVER_ADMIN", init_service)
        self.assertNotIn("POSTGRES_PASSWORD", init_service)
        workflow = (ROOT / ".github" / "workflows" / "dev-integration.yml").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("packages: read", workflow)
        self.assertNotIn("secrets.GITHUB_TOKEN", workflow)
        self.assertIn("secrets.JORT_PRIVATE_DOCKER_IMAGES", workflow)
        self.assertIn("docker login ghcr.io", workflow)


if __name__ == "__main__":
    unittest.main()
