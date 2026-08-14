import argparse
import json
import ssl
import urllib.parse
import urllib.request


GRID_LAYERS = {
    "grid_lv_mv_transformer_reach",
    "grid_lines",
    "grid_transformers",
    "grid_mv_hv_transformer_reach",
}
EXPECTED_STATIONS = {
    "OS ALKMAAR",
    "OS HEERHUGOWAARD",
    "OS HEILOO",
    "OS OUDORP",
    "OS OTERLEEK",
    "OS WARMENHUIZEN",
    "OS SCHAGEN",
}


class Client:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=context)
        )

    def get_json(self, path: str, timeout: int = 300) -> dict:
        with self.opener.open(f"{self.base_url}{path}", timeout=timeout) as response:
            return json.loads(response.read())


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def wfs_collection(
    client: Client,
    layer_id: str,
    *,
    count: int = 100,
    cql_filter: str | None = None,
) -> dict:
    parameters = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeNames": layer_id,
        "outputFormat": "application/json",
        "srsName": "EPSG:4326",
        "count": count,
    }
    if cql_filter:
        parameters["cql_filter"] = cql_filter
    query = urllib.parse.urlencode(parameters)
    return client.get_json(f"/geoserver/rdp/ows?{query}")


def json_property(value, expected_type, message: str):
    if isinstance(value, expected_type):
        return value
    if isinstance(value, str):
        decoded = json.loads(value)
        if isinstance(decoded, expected_type):
            return decoded
    raise AssertionError(message)


def validate_reach_feature(feature: dict, expected_level: str) -> str:
    geometry = feature.get("geometry", {})
    require(
        geometry.get("type") in {"Polygon", "MultiPolygon"},
        f"{expected_level} reach must preserve PC6 polygon geometry",
    )
    properties = feature.get("properties", {})
    pc6_id = str(properties.get("pc6_id", ""))
    require(
        len(pc6_id) == 6 and pc6_id[:4].isdigit() and pc6_id[4:].isalpha(),
        f"{expected_level} reach has an invalid PC6 identifier",
    )
    require(
        properties.get("reach_level") == expected_level,
        f"{expected_level} reach level drift",
    )
    require(
        properties.get("share_scope") == "absolute_pc6_to_target",
        f"{expected_level} reach share scope drift",
    )
    shares = json_property(
        properties.get("ranked_shares"),
        list,
        f"{expected_level} reach has no ranked shares",
    )
    require(
        len(shares) == int(properties.get("entity_count", 0)),
        f"{expected_level} reach share count drift",
    )
    require(shares, f"{expected_level} reach has no transformer assignment")
    require(
        abs(sum(float(item["share"]) for item in shares) - 1.0) <= 0.0001,
        f"{expected_level} reach shares do not sum to one",
    )
    require(
        shares[0]["transformer_id"]
        == properties.get("dominant_transformer_id"),
        f"{expected_level} dominant transformer drift",
    )
    expected_target_type = (
        "lv_mv_transformer"
        if expected_level == "lv_mv"
        else "mv_hv_transformer_root"
    )
    for share in shares:
        require(
            share.get("target_type") == expected_target_type,
            f"{expected_level} reach target type drift",
        )
        for evidence_field in (
            "lv_mv_transformer_ids",
            "mv_hv_transformer_ids",
            "root_bus_ids",
            "source_station_objectids",
            "match_methods",
        ):
            require(
                isinstance(share.get(evidence_field), list),
                f"{expected_level} reach lacks {evidence_field}",
            )
    json_property(
        properties.get("match_evidence"),
        dict,
        f"{expected_level} reach has no matching evidence",
    )
    return pc6_id


def check(base_url: str) -> None:
    client = Client(base_url)
    ready = client.get_json("/models/grid/ready")
    require(ready.get("status") == "ready", "Grid API is not ready")
    require(
        ready.get("data_mode") == "real_source",
        "Grid API is fixture-backed; start the normal local Compose path",
    )

    catalog = client.get_json("/models/grid/layers")
    layers = {item["id"]: item for item in catalog.get("layers", [])}
    require(set(layers) == GRID_LAYERS, "Grid API layer contract drift")
    for layer_id in GRID_LAYERS:
        count = layers[layer_id].get("runtime", {}).get("feature_count", 0)
        require(count > 0, f"{layer_id} is empty")

    for level in ("lv", "mv", "hv"):
        collection = wfs_collection(
            client,
            "grid_lines",
            count=1,
            cql_filter=f"voltage_level='{level}'",
        )
        require(
            int(collection.get("numberMatched", 0)) > 0,
            f"No {level.upper()} lines were published",
        )

    northern_lines = wfs_collection(
        client,
        "grid_lines",
        count=1,
        cql_filter="BBOX(geom,4.60,52.75,4.98,52.88,'EPSG:4326')",
    )
    require(
        int(northern_lines.get("numberMatched", 0)) > 0,
        "The published grid does not extend north into the Schagen area",
    )

    transformers = wfs_collection(
        client,
        "grid_transformers",
        cql_filter="transformer_type='mv_hv'",
    )
    require(
        int(transformers.get("numberMatched", 0)) == 7,
        "Published Grid must contain exactly seven MV/HV transformer roots",
    )
    names = {
        str(feature.get("properties", {}).get("source_station_name", "")).upper()
        for feature in transformers.get("features", [])
    }
    require(names == EXPECTED_STATIONS, "MV/HV station identity drift")

    lv_mv = wfs_collection(client, "grid_lv_mv_transformer_reach", count=10)
    mv_hv = wfs_collection(client, "grid_mv_hv_transformer_reach", count=10)
    lv_mv_count = int(lv_mv.get("numberMatched", 0))
    mv_hv_count = int(mv_hv.get("numberMatched", 0))
    require(lv_mv_count > 0, "LV/MV PC6 reach layer is empty")
    require(
        lv_mv_count == mv_hv_count,
        "LV/MV and MV/HV reach layers cover different PC6 counts",
    )
    sample_pc6 = validate_reach_feature(lv_mv["features"][0], "lv_mv")
    matching_mv_hv = wfs_collection(
        client,
        "grid_mv_hv_transformer_reach",
        count=1,
        cql_filter=f"pc6_id='{sample_pc6}'",
    )
    require(
        int(matching_mv_hv.get("numberMatched", 0)) == 1,
        "MV/HV reach is missing an LV/MV reach PC6",
    )
    validate_reach_feature(matching_mv_hv["features"][0], "mv_hv")

    print(
        "Full Grid check passed: LV/MV/HV lines through Schagen, seven "
        "MV/HV roots, and matching PC6 share layers at both transformer levels."
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1")
    args = parser.parse_args()
    check(args.base_url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
