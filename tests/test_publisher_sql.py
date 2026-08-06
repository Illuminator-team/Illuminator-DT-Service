import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "layer-publisher"))

from postgis_sql import values_template  # noqa: E402


class PublisherSqlTest(unittest.TestCase):
    def test_multipolygon_values_template_is_balanced(self):
        template = values_template(2)

        self.assertEqual(
            template,
            "(%s,%s,ST_Multi(ST_CollectionExtract(ST_MakeValid("
            "ST_SetSRID(ST_GeomFromGeoJSON(%s),4326)),3)))",
        )
        self.assertEqual(template.count("("), template.count(")"))
        self.assertEqual(template.count("%s"), 3)

    def test_values_template_rejects_missing_scalar_values(self):
        with self.assertRaisesRegex(ValueError, "must be positive"):
            values_template(0)


if __name__ == "__main__":
    unittest.main()
