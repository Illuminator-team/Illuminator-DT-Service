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


class AssignmentGrid:
    """Grid answer for one buurt with a tiny unresolved upstream share (#44)."""

    def __init__(self):
        self.request = None

    def json(self, method, path, **kwargs):
        if method == "POST":
            self.request = kwargs["json"]
            return {"status": "completed", "outputs": [{"output_id": "out-1"}]}
        return {"links": {"data": "/outputs/out-1/data"}}

    def bytes(self, path):
        row = lambda **p: {"properties": {"source_feature_id": "BU1", **p}}  # noqa: E731
        return json.dumps({"features": [
            row(row_type="source_to_lv_mv_assignment", assignment_status="assigned",
                lv_mv_transformer_id="lv-1", share=0.992),
            row(row_type="source_to_lv_mv_assignment", assignment_status="assigned",
                lv_mv_transformer_id="lv-2", share=0.008),
            row(row_type="source_to_mv_hv_derived", assignment_status="unavailable",
                mv_hv_endpoint_id=None, share=None),
            row(row_type="source_to_mv_hv_derived", assignment_status="partial",
                mv_hv_endpoint_id="hv-1", share=0.992),
            row(row_type="source_to_mv_hv_reconciliation", assignment_status=None),
        ]}).encode()


class PvPartialUpstreamTest(unittest.TestCase):
    def test_partial_mv_hv_rows_keep_the_buurt(self):
        grid = AssignmentGrid()
        inputs = {
            "geometries": {"BU1": {"type": "Point", "coordinates": [4.75, 52.63]}},
            "artifact_sha256": "a" * 64,
            "model_id": "pv", "model_version": "0.3.0", "release_commit": "c" * 40,
            "features": {"BU1": {"source_feature_version": "v1"}},
        }
        sources = profile_cache_init._pv_assignments(grid, inputs)
        self.assertEqual(grid.request["partial_upstream_coverage"], "report_assigned_part")
        self.assertEqual(
            sources["BU1"]["mv_hv"], [{"transformer_id": "hv-1", "share": 0.992}]
        )
        self.assertEqual(len(sources["BU1"]["lv_mv"]), 2)


if __name__ == "__main__":
    unittest.main()
