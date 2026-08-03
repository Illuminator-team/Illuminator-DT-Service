import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "layer-publisher"))

from pc6 import get_layer_config, load_manifest, load_pc6_records  # noqa: E402


class Pc6ContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = load_manifest(ROOT / "layer-publisher" / "layer-manifest.json")
        cls.layer = get_layer_config(
            cls.manifest, "layer:policy-tool:pc6-energy"
        )
        cls.records = load_pc6_records(
            ROOT / "policy-tool-frontend" / "data" / "alkmaar_energy_map.geojson",
            cls.layer,
        )

    def test_publication_contract(self) -> None:
        self.assertEqual(self.manifest["workspace"], "rdp")
        self.assertEqual(self.manifest["datastore"], "rdp_postgis")
        self.assertEqual(self.layer["table"], "policy_tool_pc6_energy")
        self.assertEqual(self.layer["geoserver_layer"], "policy_tool_pc6_energy")
        self.assertEqual(self.layer["source"]["crs"], "EPSG:4326")

    def test_source_has_stable_unique_feature_ids(self) -> None:
        ids = [record.postcode6 for record in self.records]
        uris = [record.uri for record in self.records]
        self.assertEqual(len(ids), 2860)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(uris), len(set(uris)))

    def test_fixture_1842em_has_required_energy_values(self) -> None:
        fixture = next(
            record for record in self.records if record.postcode6 == "1842EM"
        )
        self.assertIsInstance(fixture.p6_gasm3_2023, float)
        self.assertIsInstance(fixture.p6_kwh_2023, float)
        self.assertIsInstance(fixture.p6_kwh_productie_2023, float)
        self.assertEqual(
            fixture.uri,
            "https://reformers01.ewi.tudelft.nl/id/geo-object/pc6/1842EM",
        )

    def test_legacy_quality_assessment_is_inherited_by_every_feature(self) -> None:
        self.assertTrue(all(record.datacompleetheid == 2 for record in self.records))
        self.assertTrue(
            all(
                record.datacompleetheid_label == "redelijke betrouwbaarheid"
                for record in self.records
            )
        )
        self.assertTrue(
            all(
                record.datacompleetheid_method
                == "legacy-pc6-layer-qualitative-v1"
                for record in self.records
            )
        )

    def test_feature_hashes_are_complete_and_stable(self) -> None:
        hashes = [record.source_feature_hash for record in self.records]
        self.assertTrue(all(len(value) == 64 for value in hashes))
        self.assertEqual(len(hashes), len(set(hashes)))


if __name__ == "__main__":
    unittest.main()
