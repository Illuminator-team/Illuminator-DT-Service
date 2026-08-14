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
from wind import fetch_wind_artifact, load_wind_records  # noqa: E402

RELEASE_COMMIT = "b89bd49c717a1e301954aa0b8c1bdb98a91f8d44"
IMAGE_TAG = (
    "ghcr.io/jortgroen/wind-turbine-map-api:"
    "sha-b89bd49c717a1e301954aa0b8c1bdb98a91f8d44"
)
IMAGE_DIGEST = "sha256:820822bfa5300bc8e2126482147b1d430d075c1834bd080999334825caa21828"
DEPLOYMENT_IMAGE = f"ghcr.io/jortgroen/wind-turbine-map-api@{IMAGE_DIGEST}"
MODEL_ID = "https://reformers01.ewi.tudelft.nl/id/model/wind-turbine-map"
MODEL_VERSION = "0.2.0"
CONTRACT_VERSION = "1.0.0"
SCHEMA_CONTRACT_VERSION = "1.0.0"
QUALITY_METHOD = "WIND-DATA-COMPLETE-001"
RUN_ID = "11111111-1111-4111-8111-111111111111"
OUTPUT_ID = "22222222-2222-4222-8222-222222222222"
TIMESTAMP = "2026-08-11T12:29:10.496289Z"
FIXTURE_SHA256 = "067c2915b2a653984ca968cffe1b5aedb06549d0cea46a3d923d9dc3a7a04bd2"


def feature(number=2811, longitude=4.7523, latitude=52.593, capacity=2050.0):
    feature_id = f"wind-turbine-{number}"
    return {
        "type": "Feature",
        "id": feature_id,
        "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
        "properties": {
            "feature_id": feature_id,
            "persistent_uri": (
                "https://reformers01.ewi.tudelft.nl/id/wind-turbine/" + feature_id
            ),
            "source_feature_id": f"rivm_windturbines_vermogen_actueel.{number}",
            "capacity_kw": capacity,
            "capacity_unit": "kW",
            "capacity_mw": capacity / 1000,
            "capacity_mw_unit": "MW",
            "hub_height_m": 85.0,
            "hub_height_unit": "m",
            "rotor_diameter_m": 71.0,
            "rotor_diameter_unit": "m",
            "tip_height_m": 120.5,
            "tip_height_unit": "m",
            "rotor_swept_area_m2": 3959.19,
            "rotor_swept_area_unit": "m2",
            "name": None,
            "turbine_type": None,
            "municipality": "Alkmaar",
            "province": "Noord-Holland",
            "country": "Nederland",
            "surface": "land",
            "source_reference_date": "2026-01-11Z",
            "modeled_annual_energy_kwh": 3165597.025,
            "modeled_annual_energy_unit": "kWh",
            "modeled_capacity_factor": 0.176279,
            "modeled_peak_power_kw": capacity,
            "modeled_peak_power_unit": "kW",
            "modeled_profile_year": 2025,
            "modeled_profile_interval": "PT15M",
            "profile_id": f"wind-profile-2025-{feature_id}",
            "profile_transport_available": False,
            "inventory_evidence_status": "published_inventory",
            "geometry_evidence_status": "published_exact_position",
            "capacity_evidence_status": "published_nameplate",
            "derived_geometry_status": "derived_from_published_dimensions",
            "generation_evidence_status": "provisional_model_estimate",
            "quality_flags": ["missing_name", "missing_turbine_type"],
            "datacompleetheid": 2,
            "datacompleetheid_label": "published inventory with modeling assumptions",
            "datacompleetheid_rule_version": QUALITY_METHOD,
            "datacompleetheid_assessed_at": TIMESTAMP,
            "datacompleetheid_reason_codes": ["MODELED_GENERATION_CAP"],
            "datacompleetheid_evidence": {"published_geometry": True},
            "completeness_reason": "Published inventory with provisional generation.",
            "source_reference_period": "2026-01-11",
            "source_modified_at": None,
            "source_last_updated": None,
            "source_retrieved_at": "2026-08-07T08:22:14.158519Z",
            "source_evidence": {
                "inventory_source_id": "fixture-alkmaar-wind-turbines"
            },
            "limitations": ["Provisional modeled generation."],
            "data_mode": "fixture",
            "model_id": MODEL_ID,
            "model_version": MODEL_VERSION,
            "contract_version": CONTRACT_VERSION,
            "schema_contract_version": SCHEMA_CONTRACT_VERSION,
            "git_commit": RELEASE_COMMIT,
            "container_image": IMAGE_TAG,
            "model_run_at": TIMESTAMP,
            "output_generated_at": TIMESTAMP,
            "run_id": RUN_ID,
            "output_id": OUTPUT_ID,
        },
    }


def collection():
    return {
        "type": "FeatureCollection",
        "features": [
            feature(),
            feature(2824, 4.7538, 52.5959, 2300.0),
            feature(2851, 4.7571, 52.6023, 2300.0),
            feature(2865, 4.7586, 52.6052, 2300.0),
        ],
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
    def __init__(self, *, data_link=None):
        payload = collection()
        artifact = json.dumps(payload, separators=(",", ":")).encode()
        identity = {"git_commit": RELEASE_COMMIT, "container_image": IMAGE_TAG}
        self.run = {
            "run_id": RUN_ID,
            "status": "completed",
            "data_mode": "fixture",
            "outputs": [{"output_id": OUTPUT_ID}],
            **identity,
        }
        self.output = {
            "output_id": OUTPUT_ID,
            "run_id": RUN_ID,
            "layer_id": "public_wind_turbines",
            "media_type": "application/geo+json",
            "schema_contract_version": SCHEMA_CONTRACT_VERSION,
            "feature_count": 4,
            "byte_size": len(artifact),
            "sha256": hashlib.sha256(artifact).hexdigest(),
            "model_version": MODEL_VERSION,
            "data_mode": "fixture",
            "output_generated_at": TIMESTAMP,
            "links": {"data": data_link or f"/outputs/{OUTPUT_ID}/data"},
            **identity,
        }
        self.routes = {
            ("GET", "/ready"): FakeResponse(document={
                "ready": True,
                "state": "ready",
                "data_mode": "fixture",
                "initialized_at": TIMESTAMP,
                "feature_count": 4,
                "model_version": MODEL_VERSION,
                "contract_version": CONTRACT_VERSION,
            }),
            ("GET", "/metadata"): FakeResponse(document={
                "contract_version": CONTRACT_VERSION,
                "schema_contract_version": SCHEMA_CONTRACT_VERSION,
                "model": {"id": MODEL_ID, "version": MODEL_VERSION},
                "crs": {"output": "OGC:CRS84"},
                **identity,
            }),
            ("GET", "/layers"): FakeResponse(document={"layers": [{
                "id": "public_wind_turbines",
                "geometry_type": "Point",
                "expected_feature_count": 4,
                "runtime": {"data_mode": "fixture", "feature_count": 4},
            }]}),
            ("POST", "/runs"): FakeResponse(document=self.run),
            ("GET", f"/runs/{RUN_ID}"): FakeResponse(document=self.run),
            ("GET", f"/outputs/{OUTPUT_ID}"): FakeResponse(document=self.output),
            ("GET", f"/outputs/{OUTPUT_ID}/data"): FakeResponse(
                document=payload,
                content=artifact,
                content_type="application/geo+json",
            ),
        }
        self.requests = []

    def request(self, method, url, **kwargs):
        path = urlparse(url).path
        self.requests.append((method, path, kwargs.get("json")))
        return self.routes[(method, path)]


class WindContractTest(unittest.TestCase):
    def test_manifest_pins_the_merged_private_release(self):
        manifest = load_manifest(ROOT / "layer-publisher" / "layer-manifest.json")
        layer = get_layer_config(manifest, "layer:wind-turbine-map:public-turbines")

        self.assertEqual(layer["source"]["release_commit"], RELEASE_COMMIT)
        self.assertEqual(layer["source"]["container_image"], DEPLOYMENT_IMAGE)
        self.assertEqual(layer["source"]["container_digest"], IMAGE_DIGEST)
        self.assertEqual(layer["source"]["container_reported_identity"], IMAGE_TAG)
        self.assertEqual(layer["source"]["crs"], "EPSG:4326")
        self.assertEqual(layer["data_quality"]["method_version"], QUALITY_METHOD)

    def test_model_owned_fixture_is_pinned_and_has_the_stable_turbine(self):
        path = ROOT / "tests" / "fixtures" / "wind" / "alkmaar_wind_turbines_fixture.json"
        payload = path.read_text(encoding="utf-8").encode("utf-8")
        fixture = json.loads(payload)

        self.assertEqual(hashlib.sha256(payload).hexdigest(), FIXTURE_SHA256)
        self.assertTrue(fixture["fixture_only"])
        self.assertEqual(len(fixture["features"]), 4)
        stable = next(item for item in fixture["features"] if item["id"] == "wind-turbine-2811")
        self.assertEqual(stable["geometry"]["coordinates"], [4.7523, 52.593])
        self.assertGreater(stable["properties"]["capacity_kw"], 0)

    def test_geojson_contract_accepts_the_stable_fixture_output(self):
        records = load_wind_records(
            collection(),
            expected_release_commit=RELEASE_COMMIT,
            expected_container_image=IMAGE_TAG,
            expected_model_version=MODEL_VERSION,
            expected_contract_version=CONTRACT_VERSION,
            expected_schema_contract_version=SCHEMA_CONTRACT_VERSION,
            expected_data_mode="fixture",
        )

        self.assertEqual(len(records), 4)
        self.assertEqual(records[0].feature_id, "wind-turbine-2811")
        self.assertGreater(records[0].properties["capacity_kw"], 0)
        self.assertEqual(len(records[0].source_feature_hash), 64)

    def test_geojson_contract_rejects_negative_capacity(self):
        payload = collection()
        payload["features"][0]["properties"]["capacity_kw"] = -1
        with self.assertRaisesRegex(ValueError, "finite and non-negative"):
            load_wind_records(
                payload,
                expected_release_commit=RELEASE_COMMIT,
                expected_container_image=IMAGE_TAG,
                expected_model_version=MODEL_VERSION,
                expected_contract_version=CONTRACT_VERSION,
                expected_schema_contract_version=SCHEMA_CONTRACT_VERSION,
                expected_data_mode="fixture",
            )

    def test_content_hash_ignores_only_per_run_identity(self):
        first = collection()
        second = copy.deepcopy(first)
        second_properties = second["features"][0]["properties"]
        second_properties.update({
            "datacompleetheid_assessed_at": "2026-08-11T12:30:10Z",
            "model_run_at": "2026-08-11T12:30:10Z",
            "output_generated_at": "2026-08-11T12:30:11Z",
            "run_id": "33333333-3333-4333-8333-333333333333",
            "output_id": "44444444-4444-4444-8444-444444444444",
        })

        def records(payload):
            return load_wind_records(
                payload,
                expected_release_commit=RELEASE_COMMIT,
                expected_container_image=IMAGE_TAG,
                expected_model_version=MODEL_VERSION,
                expected_contract_version=CONTRACT_VERSION,
                expected_schema_contract_version=SCHEMA_CONTRACT_VERSION,
                expected_data_mode="fixture",
            )

        self.assertEqual(
            records(first)[0].source_feature_hash,
            records(second)[0].source_feature_hash,
        )
        second["features"][0]["properties"]["capacity_kw"] += 1
        self.assertNotEqual(
            records(first)[0].source_feature_hash,
            records(second)[0].source_feature_hash,
        )

    def test_http_handoff_verifies_and_returns_the_exact_artifact(self):
        session = FakeSession()
        artifact = fetch_wind_artifact(
            "http://wind-api:8080",
            expected_release_commit=RELEASE_COMMIT,
            expected_container_image=IMAGE_TAG,
            expected_container_digest=IMAGE_DIGEST,
            expected_model_version=MODEL_VERSION,
            expected_contract_version=CONTRACT_VERSION,
            expected_schema_contract_version=SCHEMA_CONTRACT_VERSION,
            expected_data_mode="fixture",
            session=session,
        )

        self.assertEqual(len(artifact.records), 4)
        self.assertEqual(artifact.container_digest, IMAGE_DIGEST)
        self.assertIn((
            "POST",
            "/runs",
            {
                "layer_id": "public_wind_turbines",
                "spatial_selection": {"type": "all"},
                "parameters": {},
            },
        ), session.requests)

    def test_http_handoff_rejects_cross_origin_output_link(self):
        session = FakeSession(data_link="https://example.invalid/output.geojson")
        with self.assertRaisesRegex(ValueError, "configured API origin"):
            fetch_wind_artifact(
                "http://wind-api:8080",
                expected_release_commit=RELEASE_COMMIT,
                expected_container_image=IMAGE_TAG,
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
        wind_init = compose.split("  wind-init:", 1)[1].split("  wind-api:", 1)[0]
        wind_api = compose.split("  wind-api:", 1)[1].split("#  --", 1)[0]

        self.assertIn(DEPLOYMENT_IMAGE, compose)
        self.assertIn(RELEASE_COMMIT, compose)
        self.assertIn("--mode\n      - real", wind_init)
        self.assertIn('user: "10001:10001"', wind_init)
        self.assertIn("read_only: true", wind_init)
        self.assertIn("no-new-privileges:true", wind_init)
        self.assertIn("service_completed_successfully", wind_api)
        self.assertNotIn("GEOSERVER_ADMIN", wind_api)
        self.assertNotIn("POSTGRES_PASSWORD", wind_api)
        self.assertIn("WIND_API_ALLOW_FIXTURE: \"true\"", local)
        self.assertIn("--allow-fixture", local)
        self.assertIn("WIND_EXPECTED_DATA_MODE: fixture", local)

        workflow = (ROOT / ".github" / "workflows" / "dev-integration.yml").read_text()
        self.assertIn("secrets.JORT_PRIVATE_DOCKER_IMAGES", workflow)
        self.assertIn("Wind layer synchronized: total=4 changed=0 deleted=0", workflow)

    def test_publisher_image_contains_the_wind_modules(self):
        dockerfile = (ROOT / "layer-publisher" / "Dockerfile").read_text()
        self.assertIn("wind.py", dockerfile)
        self.assertIn("wind_postgis.py", dockerfile)


if __name__ == "__main__":
    unittest.main()
