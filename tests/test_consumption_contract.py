import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "layer-publisher"))

from consumption import fetch_consumption_artifact, load_consumption_records  # noqa: E402
from pc6 import get_layer_config, load_manifest  # noqa: E402

RELEASE_COMMIT = "e5f44368b01bee9f4a77a409e6894f22f57f9684"
IMAGE_IDENTITY = "ghcr.io/jortgroen/consumption-map-api@sha256:a1116b2e4bfd32167c2277089523a7d1f8c82aaf82641059412c9cd03415d43e"
SOURCE_CACHE_IMAGE = "ghcr.io/jortgroen/consumption-map-source-cache@sha256:f4bcf9c44b39ee4e1e244502a220296d1a0cdfa9ed2bb21bf2667654f391ef59"
MODEL_VERSION = "0.4.0"
CONTRACT_VERSION = "reformers-consumption-v1"
QUALITY_RULE = "datacompleetheid-qualitative-v1"
RUN_ID = "run_acceptance"
OUTPUT_ID = "out_acceptance"


def consumption_feature(*, annual_electricity=40002398.257121):
    timestamp = "2026-08-07T10:00:00+00:00"
    feature_id = "consumption-electricity-area-bu03610308"
    return {
        "type": "Feature",
        "id": feature_id,
        "geometry": {
            "type": "MultiPolygon",
            "coordinates": [[[[4.74, 52.59], [4.77, 52.59], [4.77, 52.61], [4.74, 52.59]]]],
        },
        "properties": {
            "feature_id": feature_id,
            "feature_uri": "https://reformers01.ewi.tudelft.nl/id/consumption/electricity-area/BU03610308",
            "spatial_unit_type": "buurt",
            "spatial_unit_code": "BU03610308",
            "name": "Boekelermeer-Zuid",
            "annual_electricity_consumption_kwh": annual_electricity,
            "annual_electricity_kwh": annual_electricity,
            "residential_electricity_kwh": 0.0,
            "business_electricity_kwh": annual_electricity,
            "services_commerce_electricity_kwh": 11042356.673082,
            "unknown_industrial_business_electricity_kwh": 28960041.584039,
            "unknown_business_electricity_kwh": 0.0,
            "annual_value_status": "modelled combination of selected public-grid anchors",
            "residential_value_status": "CBS average-times-dwellings proxy aggregated from PC6",
            "business_value_status": "allocated_by_wijk_scaled_buurt_class_proxy",
            "allocation_method": "cbs_wijk_business_buurt_proxy_v1",
            "source_reference_period": "2023",
            "source_modified_at": None,
            "source_modified_at_status": "publisher timestamps unavailable",
            "source_retrieved_at": None,
            "source_retrieved_at_status": "date-only retrieval evidence",
            "source_retrieved_on": "2026-07-29",
            "source_ids": ["D-CONS-001", "D-CONS-020"],
            "sources": [{"source_id": "D-CONS-001", "title": "CBS PC6 2023"}],
            "quality_flags": ["business_buurt_proxy_allocation"],
            "datacompleetheid": {
                "score": 2,
                "label": "Quite accurate with assumptions",
                "rule_version": QUALITY_RULE,
                "assessed_at": timestamp,
                "evidence": {"observed": 2, "estimated": 2, "assumed": 2, "missing": 1},
                "reason_codes": ["business_buurt_proxy_allocation"],
                "explanation": "Source anchors are present, but documented assumptions remain.",
            },
            "model_run_at": timestamp,
            "output_generated_at": timestamp,
            "model_version": MODEL_VERSION,
            "metadata_contract_version": CONTRACT_VERSION,
            "release_commit": RELEASE_COMMIT,
            "container_image": IMAGE_IDENTITY,
            "provenance": {"state_fingerprint": "a" * 64},
        },
    }


def collection():
    return {
        "type": "FeatureCollection",
        "name": "electricity_consumption_areas",
        "crs": "urn:ogc:def:crs:OGC::CRS84",
        "features": [consumption_feature()],
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
    def __init__(self, *, data_url=None):
        document = collection()
        identity = {
            "release_commit": RELEASE_COMMIT,
            "container_image": IMAGE_IDENTITY,
        }
        payload = json.dumps(
            document, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8") + b"\n"
        self.output = {
            "output_id": OUTPUT_ID,
            "run_id": RUN_ID,
            "layer_id": "electricity_consumption_areas",
            "status": "available",
            "media_type": "application/geo+json",
            "feature_count": 1,
            "semantic_sha256": hashlib.sha256(payload).hexdigest(),
            "output_generated_at": "2026-08-07T10:00:00+00:00",
            "data_url": data_url or f"/outputs/{OUTPUT_ID}/data",
        }
        self.run = {
            "run_id": RUN_ID,
            "status": "succeeded",
            "output_ids": [OUTPUT_ID],
            "outputs": [self.output],
            **identity,
        }
        self.stored_run = {key: value for key, value in self.run.items() if key != "outputs"}
        self.routes = {
            ("GET", "/readyz"): FakeResponse(document={
                "status": "ready",
                "reasons": [],
                "runtime_state": {
                    "state_fingerprint": "a" * 64,
                    "initialized_at": "2026-08-07T09:00:00+00:00",
                },
                **identity,
            }),
            ("GET", "/metadata"): FakeResponse(document={
                "model_id": "consumption-map",
                "model_version": MODEL_VERSION,
                "metadata_contract_version": CONTRACT_VERSION,
                "release_commit": RELEASE_COMMIT,
                "container_image": IMAGE_IDENTITY,
                "ready": True,
            }),
            ("GET", "/layers"): FakeResponse(document={
                "layers": [{
                    "layer_id": "electricity_consumption_areas",
                    "media_type": "application/geo+json",
                }]
            }),
            ("POST", "/v1/runs"): FakeResponse(document=self.run),
            ("GET", f"/v1/runs/{RUN_ID}"): FakeResponse(document=self.stored_run),
            ("GET", f"/v1/outputs/{OUTPUT_ID}"): FakeResponse(document=self.output),
            ("GET", f"/outputs/{OUTPUT_ID}/data"): FakeResponse(
                document=document, content=payload, content_type="application/geo+json"
            ),
        }
        self.requests = []

    def request(self, method, url, **kwargs):
        path = urlparse(url).path
        self.requests.append((method, path, kwargs.get("json")))
        return self.routes[(method, path)]


class ConsumptionContractTest(unittest.TestCase):
    def test_manifest_pins_consumption_release_and_geoserver_layer(self):
        manifest = load_manifest(ROOT / "layer-publisher" / "layer-manifest.json")
        layer = get_layer_config(
            manifest, "layer:consumption-map:electricity-areas"
        )
        self.assertEqual(layer["source"]["release_commit"], RELEASE_COMMIT)
        self.assertEqual(layer["source"]["container_image"], IMAGE_IDENTITY)
        self.assertEqual(layer["source"]["source_cache_image"], SOURCE_CACHE_IMAGE)
        self.assertEqual(
            layer["services"]["qualified_layer"],
            "rdp:consumption_electricity_areas",
        )
        self.assertEqual(layer["data_quality"]["method_version"], QUALITY_RULE)

    def test_boekelermeer_fixture_is_accepted(self):
        records = load_consumption_records(
            collection(),
            expected_release_commit=RELEASE_COMMIT,
            expected_container_image=IMAGE_IDENTITY,
            expected_model_version=MODEL_VERSION,
            expected_metadata_contract_version=CONTRACT_VERSION,
            expected_quality_rule_version=QUALITY_RULE,
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].properties["spatial_unit_code"], "BU03610308")
        self.assertEqual(records[0].properties["name"], "Boekelermeer-Zuid")
        self.assertGreater(records[0].properties["annual_electricity_kwh"], 0)
        self.assertEqual(records[0].properties["datacompleetheid"], 2)

    def test_negative_consumption_is_rejected(self):
        document = collection()
        document["features"][0] = consumption_feature(annual_electricity=-1)
        with self.assertRaisesRegex(ValueError, "finite and non-negative"):
            load_consumption_records(
                document,
                expected_release_commit=RELEASE_COMMIT,
                expected_container_image=IMAGE_IDENTITY,
                expected_model_version=MODEL_VERSION,
                expected_metadata_contract_version=CONTRACT_VERSION,
                expected_quality_rule_version=QUALITY_RULE,
            )

    def test_annual_compatibility_field_drift_is_rejected(self):
        document = collection()
        document["features"][0]["properties"][
            "annual_electricity_consumption_kwh"
        ] += 1
        with self.assertRaisesRegex(ValueError, "compatibility fields drift"):
            load_consumption_records(
                document,
                expected_release_commit=RELEASE_COMMIT,
                expected_container_image=IMAGE_IDENTITY,
                expected_model_version=MODEL_VERSION,
                expected_metadata_contract_version=CONTRACT_VERSION,
                expected_quality_rule_version=QUALITY_RULE,
            )

    def test_unavailable_component_values_remain_null(self):
        document = collection()
        properties = document["features"][0]["properties"]
        properties["business_electricity_kwh"] = None
        properties["services_commerce_electricity_kwh"] = None
        properties["unknown_industrial_business_electricity_kwh"] = None
        properties["unknown_business_electricity_kwh"] = None
        records = load_consumption_records(
            document,
            expected_release_commit=RELEASE_COMMIT,
            expected_container_image=IMAGE_IDENTITY,
            expected_model_version=MODEL_VERSION,
            expected_metadata_contract_version=CONTRACT_VERSION,
            expected_quality_rule_version=QUALITY_RULE,
        )
        self.assertIsNone(records[0].properties["business_electricity_kwh"])

    def test_run_metadata_does_not_rewrite_unchanged_consumption_features(self):
        first = load_consumption_records(
            collection(),
            expected_release_commit=RELEASE_COMMIT,
            expected_container_image=IMAGE_IDENTITY,
            expected_model_version=MODEL_VERSION,
            expected_metadata_contract_version=CONTRACT_VERSION,
            expected_quality_rule_version=QUALITY_RULE,
        )[0]
        rerun = collection()
        properties = rerun["features"][0]["properties"]
        properties["model_run_at"] = "2026-08-08T10:00:00+00:00"
        properties["output_generated_at"] = "2026-08-08T10:00:00+00:00"
        properties["datacompleetheid"]["assessed_at"] = "2026-08-08T10:00:00+00:00"
        second = load_consumption_records(
            rerun,
            expected_release_commit=RELEASE_COMMIT,
            expected_container_image=IMAGE_IDENTITY,
            expected_model_version=MODEL_VERSION,
            expected_metadata_contract_version=CONTRACT_VERSION,
            expected_quality_rule_version=QUALITY_RULE,
        )[0]
        self.assertEqual(first.source_feature_hash, second.source_feature_hash)

        properties["annual_electricity_kwh"] += 1
        properties["annual_electricity_consumption_kwh"] += 1
        changed = load_consumption_records(
            rerun,
            expected_release_commit=RELEASE_COMMIT,
            expected_container_image=IMAGE_IDENTITY,
            expected_model_version=MODEL_VERSION,
            expected_metadata_contract_version=CONTRACT_VERSION,
            expected_quality_rule_version=QUALITY_RULE,
        )[0]
        self.assertNotEqual(first.source_feature_hash, changed.source_feature_hash)

    def test_http_handoff_uses_bounded_alkmaar_request(self):
        session = FakeSession()
        artifact = fetch_consumption_artifact(
            "http://consumption-api:8080",
            expected_release_commit=RELEASE_COMMIT,
            expected_container_image=IMAGE_IDENTITY,
            expected_model_version=MODEL_VERSION,
            expected_metadata_contract_version=CONTRACT_VERSION,
            expected_quality_rule_version=QUALITY_RULE,
            session=session,
        )
        self.assertEqual(artifact.output_id, OUTPUT_ID)
        self.assertEqual(len(artifact.records), 1)
        self.assertIn(
            (
                "POST",
                "/v1/runs",
                {
                    "dataset_id": "alkmaar_2023",
                    "layer_ids": ["electricity_consumption_areas"],
                    "selection": {"municipality_code": "GM0361"},
                },
            ),
            session.requests,
        )

    def test_cross_origin_data_url_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "configured API origin"):
            fetch_consumption_artifact(
                "http://consumption-api:8080",
                expected_release_commit=RELEASE_COMMIT,
                expected_container_image=IMAGE_IDENTITY,
                expected_model_version=MODEL_VERSION,
                expected_metadata_contract_version=CONTRACT_VERSION,
                expected_quality_rule_version=QUALITY_RULE,
                session=FakeSession(data_url="https://example.invalid/output.geojson"),
            )

    def test_compose_keeps_shared_credentials_out_of_consumption(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        service = compose.split("  consumption-api:", 1)[1].split("  ##", 1)[0]
        self.assertNotIn("GEOSERVER_ADMIN", service)
        self.assertNotIn("POSTGRES_PASSWORD", service)
        self.assertNotIn("concumption-map.git", compose)
        self.assertIn(IMAGE_IDENTITY, service)
        self.assertIn("CONSUMPTION_CONTAINER_IMAGE", service)
        self.assertIn("read_only: true", service)


if __name__ == "__main__":
    unittest.main()
