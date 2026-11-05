import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "policy-tool-backend"))

import profile_cache_init  # noqa: E402


class FailedRunPv:
    def bytes(self, path):
        feature = lambda i, r, c: {  # noqa: E731
            "properties": {
                "source_feature_id": i,
                "residential_kwp_real": r,
                "commercial_kwp_derived": c,
                "source_feature_hash": "h",
            },
            "geometry": {},
        }
        return json.dumps({"features": [feature("A", 1, 2), feature("B", 3, 1)]}).encode()

    def json(self, method, path, **kwargs):
        return {"run_id": "run-1", "status": "failed", "output_ids": [], "errors": ["boom"]}


class PvProfileRunFailureTest(unittest.TestCase):
    def test_failed_pv_run_reports_run_id_and_errors(self):
        with self.assertRaises(profile_cache_init.CacheBuildError) as caught:
            profile_cache_init._pv_inputs(
                FailedRunPv(), metadata={}, capacity_output={"links": {"data": "/x"}}
            )
        message = str(caught.exception)
        self.assertIn("run-1", message)
        self.assertIn("failed", message)
        self.assertIn("boom", message)


if __name__ == "__main__":
    unittest.main()
