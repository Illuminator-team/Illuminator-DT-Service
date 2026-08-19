import gzip
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "policy-tool-backend"))

from transformer_baseline import BaselineUnavailable, TransformerBaselineStore  # noqa: E402
from profile_cache_init import source_identity  # noqa: E402


def baseline_document():
    count = 35040
    return {
        "schema_version": "transformer-profile-baseline-v1",
        "profile_year": 2023,
        "resolution": "PT15M",
        "start": "2022-12-31T23:00:00Z",
        "end": "2023-12-31T23:00:00Z",
        "timestamps": [f"2023-profile-{index}" for index in range(count)],
        "shapes": {
            "demand_kw_per_kwh": [0.001] * count,
            "pv_residential_kw_per_kwp": [0.2] * count,
            "pv_commercial_kw_per_kwp": [0.1] * count,
        },
        "sources": {
            "pc6": {
                "1483AA": {
                    "lv_mv": [{"transformer_id": "lv-1", "share": 0.75}],
                    "mv_hv": [{"transformer_id": "mv-1", "share": 1.0}],
                }
            },
            "cbs_buurt": {
                "BU03610302": {
                    "lv_mv": [{"transformer_id": "lv-1", "share": 0.25}],
                    "mv_hv": [{"transformer_id": "mv-1", "share": 1.0}],
                }
            },
        },
        "targets": {
            "lv_mv": {
                "lv-1": {
                    "transformer_name": "LV one",
                    "demand_annual_kwh": 1000.0,
                    "pv_residential_kwp": 20.0,
                    "pv_commercial_kwp": 10.0,
                    "datacompleetheid": 1,
                    "contributor_counts": {"consumption_pc6": 4, "pv_cbs_buurt": 2},
                }
            },
            "mv_hv": {
                "mv-1": {
                    "transformer_name": "MV one",
                    "demand_annual_kwh": 3000.0,
                    "pv_residential_kwp": 40.0,
                    "pv_commercial_kwp": 30.0,
                    "datacompleetheid": 1,
                    "contributor_counts": {"consumption_pc6": 12, "pv_cbs_buurt": 5},
                }
            },
        },
        "overall_datacompleetheid": 1,
        "source_models": [{"model": "consumption"}, {"model": "pv"}, {"model": "grid"}],
        "limitations": [{"code": "pv_weather_calendar_projected_to_2023"}],
        "cache_fingerprint": "fixture-cache",
    }


def write_baseline(path: Path) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump(baseline_document(), handle)


def test_baseline_returns_complete_connected_transformer_totals(tmp_path):
    path = tmp_path / "baseline.json.gz"
    write_baseline(path)

    response = TransformerBaselineStore(path).response_for("pc6", "1483aa")

    assert response["feature"]["source_feature_id"] == "1483AA"
    assert response["profile"]["scope"] == "complete_connected_transformer_baseline"
    assert response["profile"]["profile_year"] == 2023
    assert response["result"]["persistence"] == "precomputed_baseline"
    lv_target = response["result"]["source_to_lv_mv"]["targets"][0]
    assert lv_target["selected_source_share"] == 0.75
    assert lv_target["contributor_counts"] == {
        "consumption_pc6": 4,
        "pv_cbs_buurt": 2,
    }
    assert len(lv_target["points"]) == 35040
    assert lv_target["points"][0] == {
        "timestamp": "2023-profile-0",
        "demand_power_kw": 1.0,
        "production_power_kw": -5.0,
        "net_power_kw": -4.0,
    }


def test_baseline_returns_same_transformer_total_for_pv_selection(tmp_path):
    path = tmp_path / "baseline.json.gz"
    write_baseline(path)
    store = TransformerBaselineStore(path)

    pc6 = store.response_for("pc6", "1483AA")
    pv = store.response_for("cbs_buurt", "BU03610302")

    assert (
        pc6["result"]["source_to_lv_mv"]["targets"][0]["points"]
        == pv["result"]["source_to_lv_mv"]["targets"][0]["points"]
    )
    assert pv["result"]["source_to_lv_mv"]["targets"][0]["selected_source_share"] == 0.25


def test_baseline_fails_closed_for_unmapped_source(tmp_path):
    path = tmp_path / "baseline.json.gz"
    write_baseline(path)

    try:
        TransformerBaselineStore(path).response_for("pc6", "9999ZZ")
    except BaselineUnavailable as exc:
        assert "No fixed-year transformer baseline" in str(exc)
    else:
        raise AssertionError("unmapped source must fail closed")


def test_source_identity_tracks_the_latest_pv_capacity_artifact(tmp_path):
    (tmp_path / "state.json").write_text(
        json.dumps(
            {
                "dataset_id": "consumption-dataset",
                "state_fingerprint": "consumption-state",
                "source_cache_sha256": "consumption-cache",
                "residential_pc6_profile_feature_count": 42,
            }
        ),
        encoding="utf-8",
    )

    class StubClient:
        def __init__(self, responses):
            self.responses = responses

        def json(self, method, path):
            assert method == "GET"
            return self.responses[path]

    grid = StubClient(
        {
            "/ready": {
                "grid_data_version": "grid-data-v1",
                "data_mode": "real_source",
            }
        }
    )
    pv = StubClient(
        {
            "/ready": {"model_version": "0.3.0", "config_fingerprint": "config-v1"},
            "/metadata": {
                "release_commit": "release-v1",
                "container_image": "image-v1",
                "links": {"latest_output": "/outputs/capacity-v2"},
            },
            "/outputs/capacity-v2": {
                "output_id": "capacity-v2",
                "sha256": "artifact-v2",
            },
        }
    )

    identity = source_identity(tmp_path, grid, pv)

    assert identity["pv"]["capacity_output_id"] == "capacity-v2"
    assert identity["pv"]["capacity_artifact_sha256"] == "artifact-v2"
