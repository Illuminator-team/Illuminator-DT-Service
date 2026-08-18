import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "layer-publisher"))

from publication_scope import MODEL_PUBLICATION_ORDER, parse_publish_models


class PublicationScopeTests(unittest.TestCase):
    def test_scope_module_is_packaged_in_publisher_image(self):
        dockerfile = (ROOT / "layer-publisher" / "Dockerfile").read_text(
            encoding="utf-8"
        )
        self.assertIn("publication_scope.py", dockerfile)

    def test_unset_blank_and_all_select_every_model(self):
        self.assertEqual(parse_publish_models(None), MODEL_PUBLICATION_ORDER)
        self.assertEqual(parse_publish_models("  "), MODEL_PUBLICATION_ORDER)
        self.assertEqual(parse_publish_models("ALL"), MODEL_PUBLICATION_ORDER)

    def test_subset_is_normalized_and_uses_canonical_order(self):
        self.assertEqual(
            parse_publish_models(" heat,grid,HEAT "),
            ("grid", "heat"),
        )

    def test_unknown_model_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unknown model.*typo"):
            parse_publish_models("heat,typo")

    def test_all_cannot_be_combined_with_a_subset(self):
        with self.assertRaisesRegex(ValueError, "cannot combine 'all'"):
            parse_publish_models("all,heat")


if __name__ == "__main__":
    unittest.main()
