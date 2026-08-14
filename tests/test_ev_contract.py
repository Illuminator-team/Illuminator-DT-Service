import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "layer-publisher"))

from ev import fetch_ev_artifact, load_ev_records  # noqa: E402
from pc6 import get_layer_config, load_manifest  # noqa: E402

RELEASE_COMMIT = "54a894cc7c96c7d8c27e344ee2724012d5ae4e3d"
IMAGE_IDENTITY = "ghcr.io/jortgroen/ev-map-api@sha256:94050f345344626b8c05d42abc116fbfc57f7578a450bf9662be2ebe56525aec"
MODEL_VERSION = "0.3.0"
CONTRACT_VERSION = "1.0.0"
QUALITY_METHOD = "EV-DATA-COMPLETE-001"
RUN_ID = "run_acceptance"
OUTPUT_ID = "out_acceptance"


def ev_feature(*, annual_energy=44009.0):
    timestamp = "2026-08-03T09:22:06+00:00"
    feature_id = "ev-charger-NL-ALL-NLLOC018787"
    return {
        "type": "Feature",
        "id": feature_id,
        "geometry": {"type": "Point", "coordinates": [4.755039, 52.605686]},
        "properties": {
            "feature_id": feature_id,
            "feature_uri": f"https://reformers01.ewi.tudelft.nl/id/{feature_id}",
            "source_feature_id": "NL-ALL-NLLOC018787",
            "address": "Diamantweg 10",
            "operator_name": "Allego",
            "cpo_id": "ALL",
            "reported_open": False,
            "connector_count": 6,
            "available_connector_count": 6,
            "max_power_kw": 11.0,
            "connector_types": ["IEC_62196_T2"],
            "power_types": ["AC3"],
            "source_feature_modified_at": timestamp,
            "linked_connector_count": 6,
            "unsupported_connector_count": 0,
            "modeled_annual_energy_kwh": annual_energy,
            "modeled_annual_peak_kw": 55.0,
            "profile_available": True,
            "profile_summary_kind": "annual_energy_and_peak_from_full_profile",
            "datacompleetheid": 2,
            "datacompleetheid_label": "quite accurate",
            "datacompleetheid_method_version": QUALITY_METHOD,
            "datacompleetheid_assessed_at": timestamp,
            "datacompleetheid_evidence": {
                "observed": ["source point", "connector inventory"],
                "estimated": ["charging profile"],
                "assumed": [],
                "missing": [],
            },
            "completeness_reason": "Source-backed inventory with modelled demand.",
            "model_id": "ev-map",
            "model_version": MODEL_VERSION,
            "metadata_contract_version": CONTRACT_VERSION,
            "release_commit": RELEASE_COMMIT,
            "container_image": IMAGE_IDENTITY,
            "model_run_at": timestamp,
            "output_generated_at": timestamp,
            "source_retrieved_at": timestamp,
            "output_id": OUTPUT_ID,
        },
    }


def collection():
    return {
        "type": "FeatureCollection",
        "name": "public_ev_chargers",
        "metadata": {
            "model_id": "ev-map",
            "model_version": MODEL_VERSION,
            "metadata_contract_version": CONTRACT_VERSION,
            "release_commit": RELEASE_COMMIT,
            "container_image": IMAGE_IDENTITY,
            "layer_id": "public_ev_chargers",
        },
        "features": [ev_feature()],
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
        payload = json.dumps(collection(), separators=(",", ":")).encode("utf-8")
        identity = {"release_commit": RELEASE_COMMIT, "container_image": IMAGE_IDENTITY}
        self.run = {
            "run_id": RUN_ID,
            "status": "succeeded",
            "input": {
                "output_type": "charger_layer",
                "spatial_selection": {"type": "all"},
                "time_window": None,
                "parameters": {},
            },
            "output_ids": [OUTPUT_ID],
            "links": {"self": f"/runs/{RUN_ID}", "outputs": [f"/outputs/{OUTPUT_ID}"]},
            **identity,
        }
        self.output = {
            "output_id": OUTPUT_ID,
            "status": "available",
            "layer_id": "public_ev_chargers",
            "media_type": "application/geo+json",
            "feature_count": 1,
            "byte_size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "output_generated_at": "2026-08-03T09:22:06+00:00",
            "model_version": MODEL_VERSION,
            "metadata_contract_version": CONTRACT_VERSION,
            "datacompleetheid_method_version": QUALITY_METHOD,
            "links": {"data": data_link or f"/outputs/{OUTPUT_ID}/data"},
            **identity,
        }
        self.routes = {
            ("GET", "/ready"): FakeResponse(document={
                "ready": True,
                "state": "ready",
                "model_version": MODEL_VERSION,
                "runtime_artifact_sha256": "a" * 64,
                "profile_runtime_artifact_sha256": "b" * 64,
                **identity,
            }),
            ("GET", "/metadata"): FakeResponse(document={
                "model": {"id": "ev-map", "version": MODEL_VERSION},
                "metadata_contract_version": CONTRACT_VERSION,
                "runtime": identity,
            }),
            ("GET", "/layers"): FakeResponse(document={
                "layers": [{"id": "public_ev_chargers", "geometry_type": "Point"}],
                **identity,
            }),
            ("POST", "/runs"): FakeResponse(document=self.run),
            ("GET", f"/runs/{RUN_ID}"): FakeResponse(document=self.run),
            ("GET", f"/outputs/{OUTPUT_ID}"): FakeResponse(document=self.output),
            ("GET", f"/outputs/{OUTPUT_ID}/data"): FakeResponse(
                document=collection(), content=payload, content_type="application/geo+json"
            ),
        }
        self.requests = []

    def request(self, method, url, **kwargs):
        path = urlparse(url).path
        self.requests.append((method, path, kwargs.get("json")))
        return self.routes[(method, path)]


class EvContractTest(unittest.TestCase):
    def test_manifest_pins_ev_release_and_geoserver_layer(self):
        manifest = load_manifest(ROOT / "layer-publisher" / "layer-manifest.json")
        layer = get_layer_config(manifest, "layer:ev-map:public-chargers")
        self.assertEqual(layer["source"]["release_commit"], RELEASE_COMMIT)
        self.assertEqual(layer["source"]["container_image"], IMAGE_IDENTITY)
        self.assertEqual(layer["services"]["qualified_layer"], "rdp:public_ev_chargers")
        self.assertEqual(layer["data_quality"]["method_version"], QUALITY_METHOD)

    def test_fixture_charger_contract_is_accepted(self):
        records = load_ev_records(
            collection(),
            expected_release_commit=RELEASE_COMMIT,
            expected_container_image=IMAGE_IDENTITY,
            expected_model_version=MODEL_VERSION,
            expected_metadata_contract_version=CONTRACT_VERSION,
            expected_quality_method_version=QUALITY_METHOD,
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].properties["address"], "Diamantweg 10")
        self.assertEqual(records[0].properties["connector_count"], 6)
        self.assertGreater(records[0].properties["modeled_annual_energy_kwh"], 0)

    def test_negative_energy_is_rejected(self):
        document = collection()
        document["features"][0] = ev_feature(annual_energy=-1)
        with self.assertRaisesRegex(ValueError, "finite and non-negative"):
            load_ev_records(
                document,
                expected_release_commit=RELEASE_COMMIT,
                expected_container_image=IMAGE_IDENTITY,
                expected_model_version=MODEL_VERSION,
                expected_metadata_contract_version=CONTRACT_VERSION,
                expected_quality_method_version=QUALITY_METHOD,
            )

    def test_run_metadata_does_not_rewrite_unchanged_ev_features(self):
        first = load_ev_records(
            collection(),
            expected_release_commit=RELEASE_COMMIT,
            expected_container_image=IMAGE_IDENTITY,
            expected_model_version=MODEL_VERSION,
            expected_metadata_contract_version=CONTRACT_VERSION,
            expected_quality_method_version=QUALITY_METHOD,
        )[0]
        rerun = collection()
        properties = rerun["features"][0]["properties"]
        properties["model_run_at"] = "2026-08-04T09:22:06+00:00"
        properties["output_generated_at"] = "2026-08-04T09:22:06+00:00"
        properties["output_id"] = "out_rerun"
        properties["datacompleetheid_assessed_at"] = "2026-08-04T09:22:06+00:00"
        second = load_ev_records(
            rerun,
            expected_release_commit=RELEASE_COMMIT,
            expected_container_image=IMAGE_IDENTITY,
            expected_model_version=MODEL_VERSION,
            expected_metadata_contract_version=CONTRACT_VERSION,
            expected_quality_method_version=QUALITY_METHOD,
        )[0]
        self.assertEqual(first.source_feature_hash, second.source_feature_hash)

        properties["connector_count"] = 7
        changed = load_ev_records(
            rerun,
            expected_release_commit=RELEASE_COMMIT,
            expected_container_image=IMAGE_IDENTITY,
            expected_model_version=MODEL_VERSION,
            expected_metadata_contract_version=CONTRACT_VERSION,
            expected_quality_method_version=QUALITY_METHOD,
        )[0]
        self.assertNotEqual(first.source_feature_hash, changed.source_feature_hash)

    def test_http_handoff_verifies_output_and_request(self):
        session = FakeSession()
        artifact = fetch_ev_artifact(
            "http://ev-api:8000",
            expected_release_commit=RELEASE_COMMIT,
            expected_container_image=IMAGE_IDENTITY,
            expected_model_version=MODEL_VERSION,
            expected_metadata_contract_version=CONTRACT_VERSION,
            expected_quality_method_version=QUALITY_METHOD,
            session=session,
        )
        self.assertEqual(artifact.output_id, OUTPUT_ID)
        self.assertEqual(len(artifact.records), 1)
        self.assertIn(
            ("POST", "/runs", {"spatial_selection": {"type": "all"}, "parameters": {}}),
            session.requests,
        )

    def test_cross_origin_output_link_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "configured API origin"):
            fetch_ev_artifact(
                "http://ev-api:8000",
                expected_release_commit=RELEASE_COMMIT,
                expected_container_image=IMAGE_IDENTITY,
                expected_model_version=MODEL_VERSION,
                expected_metadata_contract_version=CONTRACT_VERSION,
                expected_quality_method_version=QUALITY_METHOD,
                session=FakeSession(data_link="https://example.invalid/ev.geojson"),
            )

    def test_compose_keeps_shared_credentials_out_of_ev(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        dockerfile = (ROOT / "layer-publisher" / "Dockerfile").read_text(
            encoding="utf-8"
        )
        service = compose.split("  ev-api:", 1)[1].split("  ##", 1)[0]
        self.assertNotIn("GEOSERVER_ADMIN", service)
        self.assertNotIn("POSTGRES_PASSWORD", service)
        self.assertNotIn("EV-map.git", compose)
        self.assertIn(IMAGE_IDENTITY, service)
        self.assertIn(RELEASE_COMMIT, service)
        self.assertIn("EV_IMAGE_IDENTITY", service)
        self.assertIn("ev.py", dockerfile)
        self.assertIn("ev_postgis.py", dockerfile)
        self.assertNotIn("consumption-api", compose)


if __name__ == "__main__":
    unittest.main()
