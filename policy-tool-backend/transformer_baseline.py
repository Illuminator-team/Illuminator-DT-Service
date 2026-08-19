from __future__ import annotations

import gzip
import json
import math
import re
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "transformer-profile-baseline-v1"
PC6_PATTERN = re.compile(r"^[1-9][0-9]{3}[A-Z]{2}$")
CBS_BUURT_PATTERN = re.compile(r"^BU[0-9]{8}$")


class BaselineUnavailable(RuntimeError):
    pass


class TransformerBaselineStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._document: dict[str, Any] | None = None
        self._mtime_ns: int | None = None

    def response_for(self, source_type: str, source_id: str) -> dict[str, Any]:
        document = self._load()
        normalized_id = source_id.replace(" ", "").upper()
        source_key = self._source_key(source_type, normalized_id)
        source = document["sources"][source_type].get(normalized_id)
        if source is None:
            raise BaselineUnavailable(
                f"No fixed-year transformer baseline is available for {source_key}."
            )

        shapes = document["shapes"]
        stages = {
            "source_to_lv_mv": self._stage(
                document,
                source,
                "lv_mv",
                "lv_mv_transformer",
                shapes,
            ),
            "lv_mv_to_mv_hv": self._stage(
                document,
                source,
                "mv_hv",
                "mv_hv_transformer",
                shapes,
            ),
        }
        result = {
            "contract_version": "1.0.0",
            "complete": True,
            "persistence": "precomputed_baseline",
            "aggregation_mode": "two_stage_precomputed_baseline",
            "resolution": document["resolution"],
            "start": document["start"],
            "end": document["end"],
            "profile_year": document["profile_year"],
            "overall_datacompleetheid": document["overall_datacompleetheid"],
            "source_to_lv_mv": stages["source_to_lv_mv"],
            "lv_mv_to_mv_hv": stages["lv_mv_to_mv_hv"],
            "limitations": document["limitations"],
        }
        return {
            "status": "completed",
            "feature": {
                "feature_type": source_type,
                "source_feature_id": normalized_id,
            },
            "profile": {
                "profile_year": document["profile_year"],
                "start": document["start"],
                "end": document["end"],
                "resolution": document["resolution"],
                "scope": "complete_connected_transformer_baseline",
                "cache_fingerprint": document["cache_fingerprint"],
                "source_models": document["source_models"],
            },
            "result": result,
        }

    def _load(self) -> dict[str, Any]:
        try:
            stat = self.path.stat()
        except OSError as exc:
            raise BaselineUnavailable(
                "The fixed-year transformer profile baseline has not been initialized."
            ) from exc
        if self._document is not None and self._mtime_ns == stat.st_mtime_ns:
            return self._document
        try:
            opener = gzip.open if self.path.suffix == ".gz" else open
            with opener(self.path, "rt", encoding="utf-8") as handle:
                document = json.load(handle)
            self._validate(document)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise BaselineUnavailable(
                "The fixed-year transformer profile baseline is invalid."
            ) from exc
        self._document = document
        self._mtime_ns = stat.st_mtime_ns
        return document

    @staticmethod
    def _source_key(source_type: str, source_id: str) -> str:
        patterns = {"pc6": PC6_PATTERN, "cbs_buurt": CBS_BUURT_PATTERN}
        pattern = patterns.get(source_type)
        if pattern is None or pattern.fullmatch(source_id) is None:
            raise BaselineUnavailable("The selected feature identity is invalid.")
        return f"{source_type}:{source_id}"

    @staticmethod
    def _stage(
        document: dict[str, Any],
        source: dict[str, Any],
        stage_id: str,
        transformer_level: str,
        shapes: dict[str, list[float]],
    ) -> dict[str, Any]:
        assignments = source[stage_id]
        targets = []
        for assignment in assignments:
            transformer_id = assignment["transformer_id"]
            target = document["targets"][stage_id].get(transformer_id)
            if target is None:
                raise BaselineUnavailable(
                    f"Transformer baseline target {transformer_id} is missing."
                )
            points = []
            for index, timestamp in enumerate(document["timestamps"]):
                demand = target["demand_annual_kwh"] * shapes["demand_kw_per_kwh"][index]
                production = -(
                    target["pv_residential_kwp"] * shapes["pv_residential_kw_per_kwp"][index]
                    + target["pv_commercial_kwp"] * shapes["pv_commercial_kw_per_kwp"][index]
                )
                points.append(
                    {
                        "timestamp": timestamp,
                        "demand_power_kw": demand,
                        "production_power_kw": production,
                        "net_power_kw": demand + production,
                    }
                )
            targets.append(
                {
                    "transformer_id": transformer_id,
                    "transformer_name": target["transformer_name"],
                    "transformer_level": transformer_level,
                    "datacompleetheid": target["datacompleetheid"],
                    "selected_source_share": assignment["share"],
                    "contributor_counts": target["contributor_counts"],
                    "points": points,
                }
            )
        return {"complete": bool(targets), "targets": targets}

    @staticmethod
    def _validate(document: Any) -> None:
        if not isinstance(document, dict) or document.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("baseline schema version mismatch")
        if document.get("profile_year") != 2023 or document.get("resolution") != "PT15M":
            raise ValueError("baseline time contract mismatch")
        timestamps = document.get("timestamps")
        shapes = document.get("shapes")
        if not isinstance(timestamps, list) or len(timestamps) != 35040:
            raise ValueError("baseline must contain one non-leap PT15M year")
        if not isinstance(shapes, dict):
            raise ValueError("baseline shapes are missing")
        for key in (
            "demand_kw_per_kwh",
            "pv_residential_kw_per_kwp",
            "pv_commercial_kw_per_kwp",
        ):
            values = shapes.get(key)
            if (
                not isinstance(values, list)
                or len(values) != len(timestamps)
                or any(
                    not isinstance(value, (int, float))
                    or isinstance(value, bool)
                    or not math.isfinite(value)
                    or value < 0
                    for value in values
                )
            ):
                raise ValueError(f"invalid baseline shape: {key}")
        if not isinstance(document.get("cache_fingerprint"), str):
            raise ValueError("baseline cache fingerprint is missing")
        if not isinstance(document.get("limitations"), list) or not document["limitations"]:
            raise ValueError("baseline limitations must be explicit")
        if not isinstance(document.get("source_models"), list) or not document["source_models"]:
            raise ValueError("baseline source models are missing")
        sources = document.get("sources")
        targets = document.get("targets")
        if not isinstance(sources, dict) or set(sources) != {"pc6", "cbs_buurt"}:
            raise ValueError("baseline source mappings are invalid")
        if not isinstance(targets, dict) or set(targets) != {"lv_mv", "mv_hv"}:
            raise ValueError("baseline targets are invalid")
