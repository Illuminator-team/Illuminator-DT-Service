import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PC6_PATTERN = re.compile(r"^[0-9]{4}[A-Z]{2}$")
ENERGY_FIELDS = (
    "p6_gasm3_2023",
    "p6_kwh_2023",
    "p6_kwh_productie_2023",
)


@dataclass(frozen=True)
class Pc6Record:
    postcode6: str
    uri: str
    p6_gasm3_2023: float
    p6_kwh_2023: float
    p6_kwh_productie_2023: float
    datacompleetheid: int
    datacompleetheid_label: str
    datacompleetheid_method: str
    evidence_summary: str
    source_feature_hash: str
    geometry_json: str


def load_manifest(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as handle:
        manifest = json.load(handle)

    required = {"workspace", "datastore", "layers"}
    missing = sorted(required.difference(manifest))
    if missing:
        raise ValueError(f"Publisher manifest is missing: {', '.join(missing)}")
    if not isinstance(manifest["layers"], list) or not manifest["layers"]:
        raise ValueError("Publisher manifest must define at least one layer")
    return manifest


def get_layer_config(manifest: dict[str, Any], local_id: str) -> dict[str, Any]:
    for layer in manifest["layers"]:
        if layer.get("local_id") == local_id:
            return layer
    raise ValueError(f"Layer {local_id!r} is not present in the publisher manifest")


def _numeric(properties: dict[str, Any], field: str, postcode6: str) -> float:
    value = properties.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{postcode6}: {field} must be numeric")
    return float(value)


def _feature_hash(
    properties: dict[str, Any],
    geometry: dict[str, Any],
    quality: dict[str, Any],
    uri: str,
) -> str:
    payload = {
        "geometry": geometry,
        "uri": uri,
        "data_quality": quality,
        **{field: properties[field] for field in ENERGY_FIELDS},
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def load_pc6_records(
    source_path: str | Path,
    layer_config: dict[str, Any],
) -> list[Pc6Record]:
    with Path(source_path).open(encoding="utf-8") as handle:
        collection = json.load(handle)

    if collection.get("type") != "FeatureCollection":
        raise ValueError("PC6 source must be a GeoJSON FeatureCollection")

    quality = layer_config["data_quality"]
    uri_template = layer_config["feature_uri_template"]
    records: list[Pc6Record] = []
    seen: set[str] = set()

    for feature in collection.get("features", []):
        properties = feature.get("properties") or {}
        postcode6 = str(properties.get("postcode6", "")).replace(" ", "").upper()
        if not PC6_PATTERN.fullmatch(postcode6):
            raise ValueError(f"Invalid or missing postcode6: {postcode6!r}")
        if postcode6 in seen:
            raise ValueError(f"Duplicate postcode6: {postcode6}")

        geometry = feature.get("geometry") or {}
        if geometry.get("type") != "MultiPolygon":
            raise ValueError(f"{postcode6}: geometry must be MultiPolygon")

        uri = uri_template.format(postcode6=postcode6)
        records.append(
            Pc6Record(
                postcode6=postcode6,
                uri=uri,
                p6_gasm3_2023=_numeric(properties, "p6_gasm3_2023", postcode6),
                p6_kwh_2023=_numeric(properties, "p6_kwh_2023", postcode6),
                p6_kwh_productie_2023=_numeric(
                    properties, "p6_kwh_productie_2023", postcode6
                ),
                datacompleetheid=int(quality["datacompleetheid"]),
                datacompleetheid_label=quality["datacompleetheid_label"],
                datacompleetheid_method=quality["datacompleetheid_method"],
                evidence_summary=quality["evidence_summary"],
                source_feature_hash=_feature_hash(properties, geometry, quality, uri),
                geometry_json=json.dumps(geometry, ensure_ascii=True, separators=(",", ":")),
            )
        )
        seen.add(postcode6)

    if not records:
        raise ValueError("PC6 source contains no features")
    return records
