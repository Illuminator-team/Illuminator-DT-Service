import argparse
import csv
import hashlib
import io
import json
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

PC6_LAYER = "policy_tool_pc6_energy"
PV_LAYER = "pv_capacity"
GRID_LINES_LAYER = "grid_lines"
GRID_TRANSFORMERS_LAYER = "grid_transformers"
GRID_MV_HV_REACH_LAYER = "grid_mv_hv_transformer_reach"
GRID_LV_MV_REACH_LAYER = "grid_lv_mv_transformer_reach"
WIND_LAYER = "public_wind_turbines"
EV_LAYER = "public_ev_chargers"
CONSUMPTION_LAYER = "consumption_electricity_areas"
PV_FIXTURE = "BU03610302"
PV_RELEASE_COMMIT = "4c920c47c34075831a5ad49e9d8f45d9dfac2ae7"
PV_CONTAINER_IMAGE = "ghcr.io/jortgroen/pv-map-api@sha256:b1748568535499bbb58908fd9b677ddf2f33b3569fd8c76af25672bd612478e6"
GRID_RELEASE_COMMIT = "3fe554a05b6609bb33b2f99bd26ba4701a55d971"
GRID_CONTAINER_DIGEST = "sha256:88d42d9ac15dbf6f20bbee0766ce0483abf360566f1e180b1018378b4053218c"
GRID_BBOX = [4.74454, 52.629131, 4.835248, 52.644642]
GRID_TRANSFORMER_FIXTURE = "grid-transformer-trafo_MV_LV_1157"
WIND_FIXTURE = "wind-turbine-2811"
WIND_RELEASE_COMMIT = "b89bd49c717a1e301954aa0b8c1bdb98a91f8d44"
WIND_CONTAINER_IMAGE = (
    "ghcr.io/jortgroen/wind-turbine-map-api:"
    "sha-b89bd49c717a1e301954aa0b8c1bdb98a91f8d44"
)
WIND_CONTAINER_DIGEST = "sha256:820822bfa5300bc8e2126482147b1d430d075c1834bd080999334825caa21828"
HEAT_RELEASE_COMMIT = "1f2b2c8b770e5c59efbed4ab58641b40b164845a"
HEAT_CONTAINER_DIGEST = "sha256:2a1afe08732e98b00a880cad0ed3ffff2dbc8c38c960be4c643dd5358676dbda"
HEAT_QUALITY_METHOD = "datacompleetheid-heat-net-v1"
HEAT_LAYERS = {
    "reported_neighbourhood_heat_consumers": {
        "geometry": "MultiPolygon",
        "fields": ("consumer_area_id", "reported_connected_share_pct"),
    },
    "inferred_pc6_heat_consumers": {
        "geometry": "MultiPolygon",
        "fields": ("postcode6", "heat_demand_gj_year_est"),
    },
    "registered_heat_network_developments": {
        "geometry": "MultiPolygon",
        "fields": ("development_area_id", "development_phase"),
    },
    "documented_actual_heat_sources": {
        "geometry": "Point",
        "fields": ("source_name", "technology"),
    },
    "documented_large_heat_consumers": {
        "geometry": "Point",
        "fields": ("consumer_name", "connection_evidence"),
    },
    "potential_heat_sources": {
        "geometry": "Point",
        "fields": ("source_name", "potential_thermal_capacity_mw"),
    },
}
HEAT_PC6_FIXTURE = "pc6-1812ab"
HEAT_VIEWS = {
    "reported_neighbourhood_heat_consumers": True,
    "allocated_pc6_heat_consumers": True,
    "unallocated_pc6_heat_signals": False,
    "excluded_electric_heating_pc6": False,
    "registered_heat_network_developments": True,
    "documented_actual_heat_sources": True,
    "potential_heat_sources": False,
    "documented_large_heat_consumers": True,
}
EV_RELEASE_COMMIT = "54a894cc7c96c7d8c27e344ee2724012d5ae4e3d"
EV_CONTAINER_IMAGE = "ghcr.io/jortgroen/ev-map-api@sha256:94050f345344626b8c05d42abc116fbfc57f7578a450bf9662be2ebe56525aec"
EV_FIXTURE = "NL-ALL-NLLOC018787"
CONSUMPTION_RELEASE_COMMIT = "e5f44368b01bee9f4a77a409e6894f22f57f9684"
CONSUMPTION_CONTAINER_IMAGE = "ghcr.io/jortgroen/consumption-map-api@sha256:a1116b2e4bfd32167c2277089523a7d1f8c82aaf82641059412c9cd03415d43e"
CONSUMPTION_FIXTURE = "BU03610308"
FIXTURE = "1842EM"
ORCHESTRATION_PC6 = "1483AA"
PV_ORCHESTRATION_BUURT = "BU03610709"
PV_ORCHESTRATION_FIXTURE_LV_MV = {
    "grid-transformer-trafo_MV_LV_1065",
    "grid-transformer-trafo_MV_LV_1168",
    "grid-transformer-trafo_MV_LV_183",
}
PV_ORCHESTRATION_REAL_LV_MV = {
    "grid-transformer-trafo_MV_LV_1168",
    "grid-transformer-trafo_MV_LV_183",
}
PV_ORCHESTRATION_MV_HV = "grid-transformer-mv-hv-station-585218"


class SmokeClient:
    def __init__(self, base_url: str, *, host_header: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.host_header = host_header
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=context)
        )

    def get(self, path: str, timeout: int = 60) -> tuple[int, bytes, str]:
        headers = {"Accept": "*/*", "User-Agent": "rdp-integration-smoke/1.0"}
        if self.host_header is not None:
            headers["Host"] = self.host_header
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            headers=headers,
        )
        with self.opener.open(request, timeout=timeout) as response:
            return response.status, response.read(), response.headers.get_content_type()

    def get_json(self, path: str, timeout: int = 60) -> dict:
        status, body, _ = self.get(path, timeout=timeout)
        if status != 200:
            raise AssertionError(f"{path} returned HTTP {status}")
        return json.loads(body)

    def post_json(
        self,
        path: str,
        payload: dict,
        timeout: int = 60,
        expected_status: int = 201,
    ) -> dict:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "rdp-integration-smoke/1.0",
        }
        if self.host_header is not None:
            headers["Host"] = self.host_header
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            method="POST",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
        )
        with self.opener.open(request, timeout=timeout) as response:
            require(
                response.status == expected_status,
                f"{path} returned HTTP {response.status}",
            )
            return json.loads(response.read())


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def wait_until_ready(client: SmokeClient, path: str, timeout: int = 720) -> None:
    deadline = time.monotonic() + timeout
    last_error = "not attempted"
    while time.monotonic() < deadline:
        try:
            status, _, _ = client.get(path, timeout=20)
            if status == 200:
                return
            last_error = f"HTTP {status}"
        except (OSError, urllib.error.URLError) as exc:
            last_error = str(exc)
        time.sleep(5)
    raise AssertionError(f"Timed out waiting for {path}: {last_error}")


def flatten_coordinates(value):
    if value and isinstance(value[0], (int, float)):
        yield value
        return
    for child in value:
        yield from flatten_coordinates(child)


def check_pc6_layer(client: SmokeClient) -> None:
    capabilities_query = urllib.parse.urlencode(
        {"service": "WMS", "version": "1.3.0", "request": "GetCapabilities"}
    )
    capabilities_path = f"/geoserver/wms?{capabilities_query}"
    deadline = time.monotonic() + 300
    while True:
        status, body, _ = client.get(capabilities_path)
        if status == 200 and PC6_LAYER.encode() in body:
            break
        if time.monotonic() >= deadline:
            raise AssertionError("PC6 layer missing from WMS capabilities")
        time.sleep(5)

    describe_query = urllib.parse.urlencode(
        {
            "service": "WFS",
            "version": "2.0.0",
            "request": "DescribeFeatureType",
            "typeNames": PC6_LAYER,
        }
    )
    status, body, _ = client.get(f"/geoserver/rdp/ows?{describe_query}")
    require(status == 200, "WFS DescribeFeatureType failed")
    for field in (
        "postcode6",
        "p6_gasm3_2023",
        "p6_kwh_2023",
        "p6_kwh_productie_2023",
        "datacompleetheid",
        "datacompleetheid_label",
        "datacompleetheid_method",
    ):
        require(field.encode() in body, f"WFS schema is missing {field}")

    feature_query = urllib.parse.urlencode(
        {
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typeNames": PC6_LAYER,
            "outputFormat": "application/json",
            "cql_filter": f"postcode6='{FIXTURE}'",
        }
    )
    feature_collection = client.get_json(f"/geoserver/rdp/ows?{feature_query}")
    require(feature_collection.get("numberReturned") == 1, "Fixture feature is missing")
    feature = feature_collection["features"][0]
    properties = feature["properties"]
    require(properties["postcode6"] == FIXTURE, "Unexpected fixture postcode")
    for field in ("p6_gasm3_2023", "p6_kwh_2023", "p6_kwh_productie_2023"):
        require(isinstance(properties[field], (int, float)), f"{field} is not numeric")
    require(properties["datacompleetheid"] == 2, "Unexpected datacompleetheid")
    require(
        properties["datacompleetheid_label"] == "redelijke betrouwbaarheid",
        "Unexpected datacompleetheid label",
    )
    require(
        properties["datacompleetheid_method"]
        == "legacy-pc6-layer-qualitative-v1",
        "Unexpected datacompleetheid method",
    )

    coordinates = list(flatten_coordinates(feature["geometry"]["coordinates"]))
    xs = [coordinate[0] for coordinate in coordinates]
    ys = [coordinate[1] for coordinate in coordinates]
    padding = 0.001
    bbox = f"{min(xs)-padding},{min(ys)-padding},{max(xs)+padding},{max(ys)+padding}"
    map_query = urllib.parse.urlencode(
        {
            "service": "WMS",
            "version": "1.1.1",
            "request": "GetMap",
            "layers": f"rdp:{PC6_LAYER}",
            "styles": "",
            "srs": "EPSG:4326",
            "bbox": bbox,
            "width": 256,
            "height": 256,
            "format": "image/png",
        }
    )
    status, image, content_type = client.get(f"/geoserver/rdp/wms?{map_query}")
    require(status == 200, "WMS GetMap failed")
    require(content_type == "image/png", f"Unexpected WMS content type: {content_type}")
    require(image.startswith(b"\x89PNG") and len(image) > 1000, "WMS map is empty")


def check_pv_model_api(client: SmokeClient) -> None:
    root = client.get_json("/models/pv/")
    require(root.get("status") == "healthy", "PV model liveness failed")

    readiness = client.get_json("/models/pv/ready", timeout=120)
    require(readiness.get("ready") is True, "PV model is not ready")
    require(readiness.get("state") == "ready", "PV readiness state drift")

    metadata = client.get_json("/models/pv/metadata")
    require(
        metadata.get("release_commit") == PV_RELEASE_COMMIT,
        "PV release identity drift",
    )
    require(
        metadata.get("container_image") == PV_CONTAINER_IMAGE,
        "PV container image identity drift",
    )
    require(metadata.get("capacity_method") == "model_estimated", "PV method drift")

    layers = client.get_json("/models/pv/layers")
    layer_records = layers.get("layers")
    require(isinstance(layer_records, list), "PV layers contract is missing")
    capacity_layers = [
        layer
        for layer in layer_records
        if isinstance(layer, dict) and layer.get("layer_id") == PV_LAYER
    ]
    require(len(capacity_layers) == 1, "PV capacity layer contract is missing or duplicated")

    run = client.post_json(
        "/models/pv/runs",
        {"spatial_selection": {"type": "all"}, "parameters": {}},
        timeout=1800,
    )
    require(run.get("status") == "succeeded", "PV model run failed")
    require(run.get("release_commit") == PV_RELEASE_COMMIT, "PV run identity drift")
    output_ids = run.get("output_ids", [])
    require(len(output_ids) == 1, "PV run did not return one output")

    output = client.get_json(f"/models/pv/outputs/{output_ids[0]}")
    require(output.get("layer_id") == PV_LAYER, "PV output layer drift")
    require(output.get("feature_count", 0) > 0, "PV output is empty")
    data_path = output.get("links", {}).get("data")
    require(isinstance(data_path, str) and data_path.startswith("/outputs/"), "PV data link drift")
    status, content, content_type = client.get(f"/models/pv{data_path}", timeout=120)
    require(status == 200, "PV output data request failed")
    require(content_type == "application/geo+json", "PV output media type drift")
    require(len(content) == output["byte_size"], "PV output byte size drift")
    require(hashlib.sha256(content).hexdigest() == output["sha256"], "PV output hash drift")


def check_pv_layer(client: SmokeClient) -> None:
    capabilities_query = urllib.parse.urlencode(
        {"service": "WMS", "version": "1.3.0", "request": "GetCapabilities"}
    )
    capabilities_path = f"/geoserver/wms?{capabilities_query}"
    deadline = time.monotonic() + 600
    while True:
        status, body, _ = client.get(capabilities_path)
        if status == 200 and PV_LAYER.encode() in body:
            break
        if time.monotonic() >= deadline:
            raise AssertionError("PV layer missing from WMS capabilities")
        time.sleep(5)

    describe_query = urllib.parse.urlencode(
        {
            "service": "WFS",
            "version": "2.0.0",
            "request": "DescribeFeatureType",
            "typeNames": PV_LAYER,
        }
    )
    status, body, _ = client.get(f"/geoserver/rdp/ows?{describe_query}")
    require(status == 200, "PV WFS DescribeFeatureType failed")
    for field in (
        "feature_id",
        "cbs_buurt_code",
        "buurt_name",
        "pv_capacity_kwp",
        "datacompleetheid",
        "datacompleetheid_label",
        "datacompleetheid_method_version",
        "last_updated",
        "model_version",
    ):
        require(field.encode() in body, f"PV WFS schema is missing {field}")

    feature_query = urllib.parse.urlencode(
        {
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typeNames": PV_LAYER,
            "outputFormat": "application/json",
            "cql_filter": f"cbs_buurt_code='{PV_FIXTURE}'",
        }
    )
    feature_collection = client.get_json(f"/geoserver/rdp/ows?{feature_query}")
    require(feature_collection.get("numberReturned") == 1, "PV fixture is missing")
    feature = feature_collection["features"][0]
    properties = feature["properties"]
    require(properties["cbs_buurt_code"] == PV_FIXTURE, "Unexpected PV fixture")
    require(properties["buurt_name"] == "Overdie-Oost", "PV fixture name drift")
    capacity = properties["pv_capacity_kwp"]
    require(isinstance(capacity, (int, float)) and capacity > 0, "PV fixture capacity is invalid")
    quality = properties["datacompleetheid"]
    require(isinstance(quality, int) and 0 <= quality <= 3, "PV quality score is invalid")

    coordinates = list(flatten_coordinates(feature["geometry"]["coordinates"]))
    xs = [coordinate[0] for coordinate in coordinates]
    ys = [coordinate[1] for coordinate in coordinates]
    padding = 0.001
    bbox = f"{min(xs)-padding},{min(ys)-padding},{max(xs)+padding},{max(ys)+padding}"
    map_query = urllib.parse.urlencode(
        {
            "service": "WMS",
            "version": "1.1.1",
            "request": "GetMap",
            "layers": f"rdp:{PV_LAYER}",
            "styles": "",
            "srs": "EPSG:4326",
            "bbox": bbox,
            "width": 256,
            "height": 256,
            "format": "image/png",
        }
    )
    status, image, content_type = client.get(f"/geoserver/rdp/wms?{map_query}")
    require(status == 200, "PV WMS GetMap failed")
    require(content_type == "image/png", f"Unexpected PV WMS content type: {content_type}")
    require(image.startswith(b"\x89PNG") and len(image) > 1000, "PV WMS map is empty")


def check_wind_model_api(client: SmokeClient) -> None:
    root = client.get_json("/models/wind/")
    require(root.get("status") == "alive", "Wind model liveness failed")

    readiness = client.get_json("/models/wind/ready", timeout=120)
    require(readiness.get("ready") is True, "Wind model is not ready")
    require(readiness.get("state") == "ready", "Wind readiness state drift")
    require(readiness.get("data_mode") == "fixture", "Wind fixture mode drift")
    require(readiness.get("feature_count") == 4, "Wind readiness feature count drift")

    metadata = client.get_json("/models/wind/metadata")
    require(metadata.get("git_commit") == WIND_RELEASE_COMMIT, "Wind release identity drift")
    require(
        metadata.get("container_image") == WIND_CONTAINER_IMAGE,
        "Wind container identity drift",
    )
    require(metadata.get("model", {}).get("version") == "0.2.0", "Wind version drift")
    require(metadata.get("contract_version") == "1.0.0", "Wind contract drift")

    layers = client.get_json("/models/wind/layers")
    require(len(layers.get("layers", [])) == 1, "Wind layer contract is missing")
    require(layers["layers"][0]["id"] == WIND_LAYER, "Wind layer ID drift")
    require(
        layers["layers"][0]["runtime"]["feature_count"] == 4,
        "Wind layer feature count drift",
    )

    run = client.post_json(
        "/models/wind/runs",
        {
            "layer_id": WIND_LAYER,
            "spatial_selection": {"type": "all"},
            "parameters": {},
        },
        timeout=300,
    )
    require(run.get("status") == "completed", "Wind model run failed")
    require(run.get("git_commit") == WIND_RELEASE_COMMIT, "Wind run identity drift")
    outputs = run.get("outputs", [])
    require(len(outputs) == 1, "Wind run did not return one output")

    output_id = outputs[0]["output_id"]
    output = client.get_json(f"/models/wind/outputs/{output_id}")
    require(output.get("layer_id") == WIND_LAYER, "Wind output layer drift")
    require(output.get("feature_count") == 4, "Wind output feature count drift")
    require(output.get("data_mode") == "fixture", "Wind output data mode drift")
    data_path = output.get("links", {}).get("data")
    require(
        isinstance(data_path, str) and data_path.startswith("/outputs/"),
        "Wind data link drift",
    )
    status, content, content_type = client.get(f"/models/wind{data_path}", timeout=120)
    require(status == 200, "Wind output data request failed")
    require(content_type == "application/geo+json", "Wind output media type drift")
    require(len(content) == output["byte_size"], "Wind output byte size drift")
    require(hashlib.sha256(content).hexdigest() == output["sha256"], "Wind output hash drift")


def check_wind_layer(client: SmokeClient) -> None:
    capabilities_query = urllib.parse.urlencode(
        {"service": "WMS", "version": "1.3.0", "request": "GetCapabilities"}
    )
    capabilities_path = f"/geoserver/wms?{capabilities_query}"
    deadline = time.monotonic() + 300
    while True:
        status, body, _ = client.get(capabilities_path)
        if status == 200 and WIND_LAYER.encode() in body:
            break
        if time.monotonic() >= deadline:
            raise AssertionError("Wind layer missing from WMS capabilities")
        time.sleep(5)

    describe_query = urllib.parse.urlencode({
        "service": "WFS",
        "version": "2.0.0",
        "request": "DescribeFeatureType",
        "typeNames": WIND_LAYER,
    })
    status, body, _ = client.get(f"/geoserver/rdp/ows?{describe_query}")
    require(status == 200, "Wind WFS DescribeFeatureType failed")
    for field in (
        "feature_id",
        "capacity_kw",
        "modeled_annual_energy_kwh",
        "datacompleetheid",
        "datacompleetheid_label",
        "datacompleetheid_rule_version",
        "deployment_container_digest",
    ):
        require(field.encode() in body, f"Wind WFS schema is missing {field}")

    feature_query = urllib.parse.urlencode({
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeNames": WIND_LAYER,
        "outputFormat": "application/json",
        "cql_filter": f"feature_id='{WIND_FIXTURE}'",
    })
    collection = client.get_json(f"/geoserver/rdp/ows?{feature_query}")
    require(collection.get("numberReturned") == 1, "Wind fixture is missing")
    feature = collection["features"][0]
    properties = feature["properties"]
    require(properties["feature_id"] == WIND_FIXTURE, "Wind fixture ID drift")
    require(properties["capacity_kw"] > 0, "Wind fixture capacity is not positive")
    require(properties["datacompleetheid"] == 2, "Wind fixture quality drift")
    require(
        properties["deployment_container_digest"] == WIND_CONTAINER_DIGEST,
        "Wind deployment digest drift",
    )
    require(feature["geometry"]["type"] == "Point", "Wind geometry type drift")
    longitude, latitude = feature["geometry"]["coordinates"][:2]
    require(abs(longitude - 4.7523) < 0.000001, "Wind fixture longitude drift")
    require(abs(latitude - 52.593) < 0.000001, "Wind fixture latitude drift")

    padding = 0.002
    map_query = urllib.parse.urlencode({
        "service": "WMS",
        "version": "1.1.1",
        "request": "GetMap",
        "layers": f"rdp:{WIND_LAYER}",
        "styles": "",
        "srs": "EPSG:4326",
        "bbox": (
            f"{longitude-padding},{latitude-padding},"
            f"{longitude+padding},{latitude+padding}"
        ),
        "width": 256,
        "height": 256,
        "format": "image/png",
    })
    status, image, content_type = client.get(f"/geoserver/rdp/wms?{map_query}")
    require(status == 200, "Wind WMS GetMap failed")
    require(content_type == "image/png", "Wind WMS content type drift")
    require(image.startswith(b"\x89PNG") and len(image) > 500, "Wind WMS map is empty")


def check_heat_model_api(client: SmokeClient) -> None:
    root = client.get_json("/models/heat/")
    require(root.get("status") == "alive", "Heat model liveness failed")

    readiness = client.get_json("/models/heat/ready", timeout=120)
    require(readiness.get("status") == "ready", "Heat model is not ready")
    require(readiness.get("data_mode") == "fixture", "Heat fixture mode drift")
    require(readiness.get("model_version") == "0.2.0", "Heat readiness version drift")

    metadata = client.get_json("/models/heat/metadata")
    require(metadata.get("model", {}).get("git_commit") == HEAT_RELEASE_COMMIT, "Heat release identity drift")
    require(metadata.get("model", {}).get("version") == "0.2.0", "Heat version drift")
    require(metadata.get("contract_version") == "1.0.0", "Heat contract drift")

    catalog = client.get_json("/models/heat/layers")
    by_id = {item["id"]: item for item in catalog.get("layers", [])}
    require(set(by_id) == set(HEAT_LAYERS), "Heat six-layer catalog drift")
    for layer_id, layer in by_id.items():
        require(layer["runtime"]["feature_count"] == 1, f"{layer_id} fixture count drift")
        require(layer["runtime"]["data_mode"] == "fixture", f"{layer_id} mode drift")

    run = client.post_json(
        "/models/heat/runs",
        {"layer_ids": list(HEAT_LAYERS), "selection": {"type": "all"}},
        timeout=300,
    )
    require(run.get("status") == "completed", "Heat model run failed")
    outputs = {item["layer_id"]: item for item in run.get("outputs", [])}
    require(set(outputs) == set(HEAT_LAYERS), "Heat run output catalog drift")
    for layer_id, summary in outputs.items():
        require(summary.get("feature_count") == 1, f"{layer_id} output summary drift")
        output = client.get_json(f"/models/heat/outputs/{summary['output_id']}")
        require(output.get("layer_id") == layer_id, f"{layer_id} output identity drift")
        require(output.get("feature_count") == 1, f"{layer_id} output count drift")
        data_path = output.get("links", {}).get("data")
        require(isinstance(data_path, str) and data_path.startswith("/outputs/"), f"{layer_id} data link drift")
        status, content, content_type = client.get(f"/models/heat{data_path}")
        require(status == 200, f"{layer_id} output data failed")
        require(content_type == "application/geo+json", f"{layer_id} media type drift")
        require(len(content) == output["byte_size"], f"{layer_id} byte size drift")
        require(hashlib.sha256(content).hexdigest() == output["sha256"], f"{layer_id} hash drift")
        collection = json.loads(content)
        feature = collection["features"][0]
        require(feature["properties"]["fixture_only"] is True, f"{layer_id} fixture marker drift")
        if layer_id == "inferred_pc6_heat_consumers":
            require(feature["id"] == HEAT_PC6_FIXTURE, "Heat PC6 fixture ID drift")
            require(feature["properties"]["allocated_connected_dwellings_est"] == 18, "Heat fixture dwelling drift")
            require(feature["properties"]["heat_demand_gj_year_est"] == 414, "Heat fixture demand drift")


def check_heat_layers(client: SmokeClient) -> None:
    capabilities_query = urllib.parse.urlencode(
        {"service": "WMS", "version": "1.3.0", "request": "GetCapabilities"}
    )
    capabilities_path = f"/geoserver/wms?{capabilities_query}"
    deadline = time.monotonic() + 300
    while True:
        status, body, _ = client.get(capabilities_path)
        if status == 200 and all(layer_id.encode() in body for layer_id in HEAT_LAYERS):
            break
        if time.monotonic() >= deadline:
            raise AssertionError("One or more Heat layers are missing from WMS capabilities")
        time.sleep(5)

    for layer_id, contract in HEAT_LAYERS.items():
        describe_query = urllib.parse.urlencode({
            "service": "WFS",
            "version": "2.0.0",
            "request": "DescribeFeatureType",
            "typeNames": layer_id,
        })
        status, body, _ = client.get(f"/geoserver/rdp/ows?{describe_query}")
        require(status == 200, f"{layer_id} WFS DescribeFeatureType failed")
        for field in (
            "feature_id",
            "evidence_status",
            "datacompleetheid",
            "datacompleetheid_rule_version",
            "fixture_only",
            "model_snapshot_id",
            "deployment_container_digest",
            *contract["fields"],
        ):
            require(field.encode() in body, f"{layer_id} WFS schema is missing {field}")

        feature_parameters = {
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typeNames": layer_id,
            "outputFormat": "application/json",
            "count": 1,
        }
        if layer_id == "inferred_pc6_heat_consumers":
            feature_parameters["cql_filter"] = f"feature_id='{HEAT_PC6_FIXTURE}'"
        collection = client.get_json(
            f"/geoserver/rdp/ows?{urllib.parse.urlencode(feature_parameters)}"
        )
        require(collection.get("numberReturned") == 1, f"{layer_id} fixture is missing")
        feature = collection["features"][0]
        properties = feature["properties"]
        require(properties["fixture_only"] is True, f"{layer_id} fixture marker drift")
        require(properties["datacompleetheid"] == 2, f"{layer_id} quality drift")
        require(properties["release_commit"] == HEAT_RELEASE_COMMIT, f"{layer_id} release drift")
        require(properties["deployment_container_digest"] == HEAT_CONTAINER_DIGEST, f"{layer_id} digest drift")
        require(feature["geometry"]["type"] == contract["geometry"], f"{layer_id} geometry drift")
        if layer_id == "inferred_pc6_heat_consumers":
            require(properties["feature_id"] == HEAT_PC6_FIXTURE, "Heat WFS fixture ID drift")
            require(properties["allocated_connected_dwellings_est"] == 18, "Heat WFS dwelling drift")
            require(properties["heat_demand_gj_year_est"] == 414, "Heat WFS demand drift")

        coordinates = list(flatten_coordinates(feature["geometry"]["coordinates"]))
        xs = [coordinate[0] for coordinate in coordinates]
        ys = [coordinate[1] for coordinate in coordinates]
        padding = 0.002
        map_query = urllib.parse.urlencode({
            "service": "WMS",
            "version": "1.1.1",
            "request": "GetMap",
            "layers": f"rdp:{layer_id}",
            "styles": "",
            "srs": "EPSG:4326",
            "bbox": f"{min(xs)-padding},{min(ys)-padding},{max(xs)+padding},{max(ys)+padding}",
            "width": 256,
            "height": 256,
            "format": "image/png",
        })
        status, image, content_type = client.get(f"/geoserver/rdp/wms?{map_query}")
        require(status == 200, f"{layer_id} WMS GetMap failed")
        require(content_type == "image/png", f"{layer_id} WMS content type drift")
        require(image.startswith(b"\x89PNG") and len(image) > 500, f"{layer_id} WMS map is empty")


def check_ev_model_api(client: SmokeClient) -> None:
    readiness = client.get_json("/models/ev/ready", timeout=120)
    require(readiness.get("ready") is True, "EV model is not ready")
    require(readiness.get("state") == "ready", "EV readiness state drift")
    require(readiness.get("feature_count") == 784, "EV release feature count drift")
    require(readiness.get("release_commit") == EV_RELEASE_COMMIT, "EV release identity drift")
    require(readiness.get("container_image") == EV_CONTAINER_IMAGE, "EV image identity drift")

    metadata = client.get_json("/models/ev/metadata")
    runtime = metadata.get("runtime", {})
    require(runtime.get("release_commit") == EV_RELEASE_COMMIT, "EV metadata commit drift")
    require(runtime.get("container_image") == EV_CONTAINER_IMAGE, "EV metadata image drift")

    layers = client.get_json("/models/ev/layers")
    by_layer = {item["id"]: item for item in layers.get("layers", [])}
    require(EV_LAYER in by_layer, "EV charger layer contract is missing")
    require(by_layer[EV_LAYER].get("current_feature_count") == 784, "EV layer count drift")

    run = client.post_json(
        "/models/ev/runs",
        {"spatial_selection": {"type": "all"}, "parameters": {}},
        timeout=300,
    )
    require(run.get("status") == "succeeded", "EV layer run failed")
    require(run.get("release_commit") == EV_RELEASE_COMMIT, "EV run identity drift")
    output_links = run.get("links", {}).get("outputs", [])
    require(len(output_links) == 1, "EV run did not return one output")
    output = client.get_json(f"/models/ev{output_links[0]}")
    require(output.get("layer_id") == EV_LAYER, "EV output layer drift")
    require(output.get("feature_count") == 784, "EV output feature count drift")
    data_path = output.get("links", {}).get("data")
    require(isinstance(data_path, str) and data_path.startswith("/outputs/"), "EV data link drift")
    status, content, content_type = client.get(f"/models/ev{data_path}", timeout=300)
    require(status == 200, "EV output data request failed")
    require(content_type == "application/geo+json", "EV output media type drift")
    require(len(content) == output["byte_size"], "EV output byte size drift")
    require(hashlib.sha256(content).hexdigest() == output["sha256"], "EV output hash drift")


def check_ev_layer(client: SmokeClient) -> None:
    capabilities_query = urllib.parse.urlencode(
        {"service": "WMS", "version": "1.3.0", "request": "GetCapabilities"}
    )
    capabilities_path = f"/geoserver/wms?{capabilities_query}"
    deadline = time.monotonic() + 300
    while True:
        status, body, _ = client.get(capabilities_path)
        if status == 200 and EV_LAYER.encode() in body:
            break
        if time.monotonic() >= deadline:
            raise AssertionError("EV charger layer missing from WMS capabilities")
        time.sleep(5)

    describe_query = urllib.parse.urlencode(
        {
            "service": "WFS",
            "version": "2.0.0",
            "request": "DescribeFeatureType",
            "typeNames": EV_LAYER,
        }
    )
    status, body, _ = client.get(f"/geoserver/rdp/ows?{describe_query}")
    require(status == 200, "EV WFS DescribeFeatureType failed")
    for field in (
        "source_feature_id",
        "address",
        "connector_count",
        "max_power_kw",
        "profile_available",
        "datacompleetheid",
        "datacompleetheid_method_version",
        "model_version",
    ):
        require(field.encode() in body, f"EV WFS schema is missing {field}")

    feature_query = urllib.parse.urlencode(
        {
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typeNames": EV_LAYER,
            "outputFormat": "application/json",
            "cql_filter": f"source_feature_id='{EV_FIXTURE}'",
        }
    )
    collection = client.get_json(f"/geoserver/rdp/ows?{feature_query}")
    require(collection.get("numberReturned") == 1, "EV fixture charger is missing")
    feature = collection["features"][0]
    properties = feature["properties"]
    require(properties["address"] == "Diamantweg 10", "EV fixture address drift")
    require(properties["connector_count"] == 6, "EV fixture connector count drift")
    require(properties["profile_available"] is True, "EV fixture profile link drift")
    require(0 <= properties["datacompleetheid"] <= 3, "EV fixture quality drift")

    lon, lat = feature["geometry"]["coordinates"][:2]
    padding = 0.01
    map_query = urllib.parse.urlencode(
        {
            "service": "WMS",
            "version": "1.1.1",
            "request": "GetMap",
            "layers": f"rdp:{EV_LAYER}",
            "styles": "",
            "srs": "EPSG:4326",
            "bbox": f"{lon-padding},{lat-padding},{lon+padding},{lat+padding}",
            "width": 256,
            "height": 256,
            "format": "image/png",
        }
    )
    status, image, content_type = client.get(f"/geoserver/rdp/wms?{map_query}")
    require(status == 200, "EV WMS GetMap failed")
    require(content_type == "image/png", f"Unexpected EV WMS content type: {content_type}")
    require(image.startswith(b"\x89PNG") and len(image) > 500, "EV WMS map is empty")


def check_grid_model_api(client: SmokeClient, expected_data_mode: str) -> None:
    root = client.get_json("/models/grid/")
    require(root.get("status") == "alive", "Grid model liveness failed")
    require(root.get("api_version") == "2.4.0", "Grid API version drift")

    readiness = client.get_json("/models/grid/ready", timeout=120)
    require(readiness.get("status") == "ready", "Grid model is not ready")
    require(
        readiness.get("data_mode") == expected_data_mode,
        f"Grid data mode drift: expected {expected_data_mode}",
    )
    grid_data_version = readiness.get("grid_data_version")
    require(
        isinstance(grid_data_version, str) and grid_data_version.startswith("grid-"),
        "Grid data version is missing",
    )

    metadata = client.get_json("/models/grid/metadata")
    require(metadata.get("contract_version") == "2.4.0", "Grid contract drift")
    require(
        metadata.get("model", {}).get("version") == "2.1.0",
        "Grid model version drift",
    )
    require(
        metadata.get("method", {}).get("version") == "2.1.0",
        "Grid method version drift",
    )
    release = metadata.get("release", {})
    require(
        release.get("git_commit") == GRID_RELEASE_COMMIT,
        "Grid release identity drift",
    )
    require(
        release.get("container_digest") == GRID_CONTAINER_DIGEST,
        "Grid image identity drift",
    )
    active_grid_data = metadata.get("active_grid_data", {})
    require(
        active_grid_data.get("data_mode") == expected_data_mode,
        "Grid metadata data mode drift",
    )

    layers = client.get_json("/models/grid/layers")
    by_layer = {item["id"]: item for item in layers.get("layers", [])}
    require(
        set(by_layer) == {
            GRID_LINES_LAYER,
            GRID_TRANSFORMERS_LAYER,
            GRID_LV_MV_REACH_LAYER,
            GRID_MV_HV_REACH_LAYER,
        },
        "Grid layer contract drift",
    )
    runtime_counts = {
        layer_id: layer["runtime"]["feature_count"]
        for layer_id, layer in by_layer.items()
    }
    for layer_id, feature_count in runtime_counts.items():
        require(feature_count > 0, f"{layer_id} runtime is empty")
        require(
            feature_count == active_grid_data.get("feature_counts", {}).get(layer_id),
            f"{layer_id} runtime count differs from active cache metadata",
        )
    if expected_data_mode == "fixture":
        require(runtime_counts[GRID_LINES_LAYER] == 34, "Grid line fixture count drift")
        require(
            runtime_counts[GRID_TRANSFORMERS_LAYER] == 2,
            "Grid transformer fixture count drift",
        )
        require(
            runtime_counts[GRID_LV_MV_REACH_LAYER] == 2,
            "Grid LV/MV reach fixture count drift",
        )
        require(
            runtime_counts[GRID_MV_HV_REACH_LAYER] == 2,
            "Grid MV/HV reach fixture count drift",
        )

    run = client.post_json(
        "/models/grid/runs",
        {
            "operation": "export_layers",
            "selection": {"type": "bbox", "bbox": GRID_BBOX},
            "layer_ids": [
                GRID_LINES_LAYER,
                GRID_TRANSFORMERS_LAYER,
                GRID_MV_HV_REACH_LAYER,
                GRID_LV_MV_REACH_LAYER,
            ],
            "voltage_levels": [],
            "component_ids": [],
        },
        timeout=300,
    )
    require(run.get("status") == "completed", "Grid export run failed")
    outputs = {item["layer_id"]: item for item in run.get("outputs", [])}
    for layer_id, summary in outputs.items():
        require(summary["feature_count"] > 0, f"{layer_id} bounded export is empty")
    if expected_data_mode == "fixture":
        require(outputs[GRID_LINES_LAYER]["feature_count"] == 34, "Grid line export drift")
        require(
            outputs[GRID_TRANSFORMERS_LAYER]["feature_count"] == 2,
            "Grid transformer export drift",
        )
        require(
            outputs[GRID_LV_MV_REACH_LAYER]["feature_count"] == 2,
            "Grid LV/MV reach export drift",
        )
        require(
            outputs[GRID_MV_HV_REACH_LAYER]["feature_count"] == 2,
            "Grid MV/HV reach export drift",
        )

    for layer_id, summary in outputs.items():
        output = client.get_json(f"/models/grid{summary['links']['self']}")
        require(output.get("media_type") == "application/geo+json", "Grid media type drift")
        status, content, content_type = client.get(
            f"/models/grid{summary['links']['data']}", timeout=120
        )
        require(status == 200, f"{layer_id} output data request failed")
        require(content_type == "application/geo+json", f"{layer_id} media type drift")
        require(len(content) == output["byte_size"], f"{layer_id} byte size drift")
        require(
            hashlib.sha256(content).hexdigest() == output["sha256"],
            f"{layer_id} output hash drift",
        )

    match = client.post_json(
        "/models/grid/runs",
        {
            "operation": "match_features",
            "selection": {"type": "bbox", "bbox": GRID_BBOX},
            "features": [
                {
                    "source_feature_id": "rdp-grid-smoke-point",
                    "geometry": {"type": "Point", "coordinates": [4.776, 52.632]},
                }
            ],
        },
        timeout=120,
    )
    require(match.get("status") == "completed", "Grid match run failed")
    match_output = match["outputs"][0]
    assignments = client.get_json(f"/models/grid{match_output['links']['data']}")
    require(len(assignments.get("features", [])) == 1, "Grid match output drift")
    assignment = assignments["features"][0]["properties"]
    serving_transformer_id = assignment.get("serving_transformer_id")
    require(serving_transformer_id, "Grid matching transformer evidence is missing")
    if expected_data_mode == "fixture":
        require(
            serving_transformer_id == GRID_TRANSFORMER_FIXTURE,
            "Grid matching transformer evidence drift",
        )


def check_grid_layers(client: SmokeClient) -> None:
    capabilities_query = urllib.parse.urlencode(
        {"service": "WMS", "version": "1.3.0", "request": "GetCapabilities"}
    )
    capabilities_path = f"/geoserver/wms?{capabilities_query}"
    deadline = time.monotonic() + 300
    while True:
        status, body, _ = client.get(capabilities_path)
        if (
            status == 200
            and GRID_LINES_LAYER.encode() in body
            and GRID_TRANSFORMERS_LAYER.encode() in body
            and GRID_LV_MV_REACH_LAYER.encode() in body
            and GRID_MV_HV_REACH_LAYER.encode() in body
        ):
            break
        if time.monotonic() >= deadline:
            raise AssertionError("Grid layers missing from WMS capabilities")
        time.sleep(5)

    expected_fields = {
        GRID_LINES_LAYER: (
            "component_id",
            "voltage_level",
            "length_km",
            "serving_transformer_id",
            "datacompleetheid",
            "grid_data_version",
        ),
        GRID_TRANSFORMERS_LAYER: (
            "component_id",
            "transformer_type",
            "rated_power_kva",
            "datacompleetheid",
            "grid_data_version",
        ),
        GRID_LV_MV_REACH_LAYER: (
            "component_id",
            "pc6_id",
            "dominant_transformer_id",
            "dominant_transformer_share",
            "share_scope",
            "ranked_shares",
            "matched_lv_cable_length_m",
            "fallback_used",
            "match_evidence",
            "datacompleetheid",
            "grid_data_version",
        ),
        GRID_MV_HV_REACH_LAYER: (
            "component_id",
            "pc6_id",
            "dominant_transformer_id",
            "dominant_transformer_share",
            "share_scope",
            "ranked_shares",
            "matched_lv_cable_length_m",
            "fallback_used",
            "match_evidence",
            "datacompleetheid",
            "grid_data_version",
        ),
    }
    for layer_id, fields in expected_fields.items():
        describe_query = urllib.parse.urlencode(
            {
                "service": "WFS",
                "version": "2.0.0",
                "request": "DescribeFeatureType",
                "typeNames": layer_id,
            }
        )
        status, body, _ = client.get(f"/geoserver/rdp/ows?{describe_query}")
        require(status == 200, f"{layer_id} WFS DescribeFeatureType failed")
        for field in fields:
            require(field.encode() in body, f"{layer_id} WFS schema is missing {field}")

        feature_parameters = {
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typeNames": layer_id,
            "outputFormat": "application/json",
            "count": 1,
        }
        if layer_id == GRID_TRANSFORMERS_LAYER:
            feature_parameters["cql_filter"] = f"component_id='{GRID_TRANSFORMER_FIXTURE}'"
        collection = client.get_json(
            f"/geoserver/rdp/ows?{urllib.parse.urlencode(feature_parameters)}"
        )
        require(collection.get("numberReturned") == 1, f"{layer_id} fixture is missing")
        feature = collection["features"][0]
        properties = feature["properties"]
        require(0 <= properties["datacompleetheid"] <= 3, f"{layer_id} quality drift")
        if layer_id == GRID_TRANSFORMERS_LAYER:
            require(
                properties["component_id"] == GRID_TRANSFORMER_FIXTURE,
                "Grid transformer ID drift",
            )

        if layer_id in {
            GRID_LV_MV_REACH_LAYER,
            GRID_MV_HV_REACH_LAYER,
        }:
            shares = properties["ranked_shares"]
            if isinstance(shares, str):
                shares = json.loads(shares)
            require(properties["pc6_id"], f"{layer_id} PC6 identity is missing")
            require(
                properties["share_scope"] == "absolute_pc6_to_target",
                f"{layer_id} transformer share scope drift",
            )
            require(
                len(shares) == properties["entity_count"],
                f"{layer_id} ranked share count drift",
            )
            require(
                abs(sum(float(item["share"]) for item in shares) - 1.0)
                <= 0.0001,
                f"{layer_id} transformer shares do not sum to one",
            )
            require(
                shares[0]["transformer_id"]
                == properties["dominant_transformer_id"],
                f"{layer_id} dominant transformer drift",
            )
            for share in shares:
                require(
                    share.get("target_type")
                    in {"lv_mv_transformer", "mv_hv_transformer_root"},
                    f"{layer_id} ranked target type drift",
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
                        f"{layer_id} ranked {evidence_field} is missing",
                    )
        coordinates = list(flatten_coordinates(feature["geometry"]["coordinates"]))
        xs = [coordinate[0] for coordinate in coordinates]
        ys = [coordinate[1] for coordinate in coordinates]
        padding = 0.001
        map_query = urllib.parse.urlencode(
            {
                "service": "WMS",
                "version": "1.1.1",
                "request": "GetMap",
                "layers": f"rdp:{layer_id}",
                "styles": "",
                "srs": "EPSG:4326",
                "bbox": f"{min(xs)-padding},{min(ys)-padding},{max(xs)+padding},{max(ys)+padding}",
                "width": 256,
                "height": 256,
                "format": "image/png",
            }
        )
        status, image, content_type = client.get(f"/geoserver/rdp/wms?{map_query}")
        require(status == 200, f"{layer_id} WMS GetMap failed")
        require(content_type == "image/png", f"{layer_id} WMS content type drift")
        require(image.startswith(b"\x89PNG") and len(image) > 500, f"{layer_id} WMS map is empty")


def check_ev_model_api(client: SmokeClient) -> None:
    readiness = client.get_json("/models/ev/ready", timeout=120)
    require(readiness.get("ready") is True, "EV model is not ready")
    require(readiness.get("state") == "ready", "EV readiness state drift")
    require(readiness.get("feature_count") == 784, "EV release feature count drift")
    require(readiness.get("release_commit") == EV_RELEASE_COMMIT, "EV release identity drift")
    require(readiness.get("container_image") == EV_CONTAINER_IMAGE, "EV image identity drift")

    metadata = client.get_json("/models/ev/metadata")
    runtime = metadata.get("runtime", {})
    require(runtime.get("release_commit") == EV_RELEASE_COMMIT, "EV metadata commit drift")
    require(runtime.get("container_image") == EV_CONTAINER_IMAGE, "EV metadata image drift")

    layers = client.get_json("/models/ev/layers")
    by_layer = {item["id"]: item for item in layers.get("layers", [])}
    require(EV_LAYER in by_layer, "EV charger layer contract is missing")
    require(by_layer[EV_LAYER].get("current_feature_count") == 784, "EV layer count drift")

    run = client.post_json(
        "/models/ev/runs",
        {"spatial_selection": {"type": "all"}, "parameters": {}},
        timeout=300,
    )
    require(run.get("status") == "succeeded", "EV layer run failed")
    require(run.get("release_commit") == EV_RELEASE_COMMIT, "EV run identity drift")
    output_links = run.get("links", {}).get("outputs", [])
    require(len(output_links) == 1, "EV run did not return one output")
    output = client.get_json(f"/models/ev{output_links[0]}")
    require(output.get("layer_id") == EV_LAYER, "EV output layer drift")
    require(output.get("feature_count") == 784, "EV output feature count drift")
    data_path = output.get("links", {}).get("data")
    require(isinstance(data_path, str) and data_path.startswith("/outputs/"), "EV data link drift")
    status, content, content_type = client.get(f"/models/ev{data_path}", timeout=300)
    require(status == 200, "EV output data request failed")
    require(content_type == "application/geo+json", "EV output media type drift")
    require(len(content) == output["byte_size"], "EV output byte size drift")
    require(hashlib.sha256(content).hexdigest() == output["sha256"], "EV output hash drift")


def check_ev_layer(client: SmokeClient) -> None:
    capabilities_query = urllib.parse.urlencode(
        {"service": "WMS", "version": "1.3.0", "request": "GetCapabilities"}
    )
    capabilities_path = f"/geoserver/wms?{capabilities_query}"
    deadline = time.monotonic() + 300
    while True:
        status, body, _ = client.get(capabilities_path)
        if status == 200 and EV_LAYER.encode() in body:
            break
        if time.monotonic() >= deadline:
            raise AssertionError("EV charger layer missing from WMS capabilities")
        time.sleep(5)

    describe_query = urllib.parse.urlencode(
        {
            "service": "WFS",
            "version": "2.0.0",
            "request": "DescribeFeatureType",
            "typeNames": EV_LAYER,
        }
    )
    status, body, _ = client.get(f"/geoserver/rdp/ows?{describe_query}")
    require(status == 200, "EV WFS DescribeFeatureType failed")
    for field in (
        "source_feature_id",
        "address",
        "connector_count",
        "max_power_kw",
        "profile_available",
        "datacompleetheid",
        "datacompleetheid_method_version",
        "model_version",
    ):
        require(field.encode() in body, f"EV WFS schema is missing {field}")

    feature_query = urllib.parse.urlencode(
        {
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typeNames": EV_LAYER,
            "outputFormat": "application/json",
            "cql_filter": f"source_feature_id='{EV_FIXTURE}'",
        }
    )
    collection = client.get_json(f"/geoserver/rdp/ows?{feature_query}")
    require(collection.get("numberReturned") == 1, "EV fixture charger is missing")
    feature = collection["features"][0]
    properties = feature["properties"]
    require(properties["address"] == "Diamantweg 10", "EV fixture address drift")
    require(properties["connector_count"] == 6, "EV fixture connector count drift")
    require(properties["profile_available"] is True, "EV fixture profile link drift")
    require(0 <= properties["datacompleetheid"] <= 3, "EV fixture quality drift")

    lon, lat = feature["geometry"]["coordinates"][:2]
    padding = 0.01
    map_query = urllib.parse.urlencode(
        {
            "service": "WMS",
            "version": "1.1.1",
            "request": "GetMap",
            "layers": f"rdp:{EV_LAYER}",
            "styles": "",
            "srs": "EPSG:4326",
            "bbox": f"{lon-padding},{lat-padding},{lon+padding},{lat+padding}",
            "width": 256,
            "height": 256,
            "format": "image/png",
        }
    )
    status, image, content_type = client.get(f"/geoserver/rdp/wms?{map_query}")
    require(status == 200, "EV WMS GetMap failed")
    require(content_type == "image/png", f"Unexpected EV WMS content type: {content_type}")
    require(image.startswith(b"\x89PNG") and len(image) > 500, "EV WMS map is empty")


def check_consumption_model_api(client: SmokeClient) -> None:
    readiness = client.get_json("/models/consumption/readyz", timeout=120)
    require(readiness.get("status") == "ready", "Consumption model is not ready")
    require(readiness.get("reasons") == [], "Consumption readiness reasons drift")
    require(
        readiness.get("release_commit") == CONSUMPTION_RELEASE_COMMIT,
        "Consumption release identity drift",
    )
    require(
        readiness.get("container_image") == CONSUMPTION_CONTAINER_IMAGE,
        "Consumption image identity drift",
    )
    require(
        readiness.get("runtime_state", {}).get("feature_count") == 67,
        "Consumption source feature count drift",
    )

    metadata = client.get_json("/models/consumption/metadata")
    require(metadata.get("model_id") == "consumption-map", "Consumption model ID drift")
    require(metadata.get("model_version") == "0.4.0", "Consumption model version drift")
    require(metadata.get("ready") is True, "Consumption metadata is not ready")

    layers = client.get_json("/models/consumption/layers")
    records = {item["layer_id"]: item for item in layers.get("layers", [])}
    require(
        "electricity_consumption_areas" in records,
        "Consumption annual layer contract is missing",
    )

    accepted = client.post_json(
        "/models/consumption/v1/runs",
        {
            "dataset_id": "alkmaar_2023",
            "layer_ids": ["electricity_consumption_areas"],
            "selection": {"municipality_code": "GM0361"},
        },
        timeout=300,
        expected_status=202,
    )
    run_id = accepted.get("run_id")
    require(isinstance(run_id, str) and run_id, "Consumption run ID is missing")
    deadline = time.monotonic() + 60
    while True:
        run = client.get_json(f"/models/consumption/v1/runs/{run_id}")
        if run.get("status") == "succeeded":
            break
        require(run.get("status") != "failed", "Consumption run failed")
        require(time.monotonic() < deadline, "Consumption run timed out")
        time.sleep(0.25)
    require(run.get("release_commit") == CONSUMPTION_RELEASE_COMMIT, "Consumption run identity drift")
    output_ids = run.get("output_ids", [])
    require(len(output_ids) == 1, "Consumption run did not return one output")
    output = client.get_json(f"/models/consumption/v1/outputs/{output_ids[0]}")
    require(output.get("feature_count") == 67, "Consumption output feature count drift")
    status, content, content_type = client.get(
        f"/models/consumption/v1/outputs/{output_ids[0]}/data",
        timeout=300,
    )
    require(status == 200, "Consumption output data request failed")
    require(content_type == "application/geo+json", "Consumption media type drift")
    require(content.endswith(b"\n"), "Consumption output lost canonical newline")
    require(
        hashlib.sha256(content).hexdigest() == output["semantic_sha256"],
        "Consumption output byte hash drift",
    )


def check_congestion_model_api(client: SmokeClient) -> None:
    readiness = client.get_json("/models/congestion/ready")
    require(readiness.get("status") == "ready", "Congestion model is not ready")

    metadata = client.get_json("/models/congestion/metadata")
    require(
        metadata.get("service") == "congestion-backend",
        "Congestion service identity drift",
    )
    require(metadata.get("service_version") == "0.4.1", "Congestion version drift")
    require(metadata.get("contract_version") == "1.0.0", "Congestion contract drift")
    require(metadata.get("temporal_resolution") == "PT15M", "Congestion resolution drift")
    require(metadata.get("canonical_unit") == "kW", "Congestion unit drift")
    require(metadata.get("adapter_mode") == "http", "Congestion adapter mode drift")
    require(metadata.get("synthetic") is False, "Congestion unexpectedly uses synthetic data")
    require(
        metadata.get("grid_hierarchy_contract", {}).get("api_contract_version")
        == "2.2.0",
        "Congestion strict Grid contract drift",
    )
    provisional = metadata.get("grid_hierarchy_contract", {}).get(
        "provisional_opt_in", {}
    )
    require(
        provisional.get("hierarchy_policy") == "nearest_electrical_root_v1",
        "Congestion provisional Grid policy drift",
    )
    require(
        provisional.get("api_contract_version") == "2.4.0"
        and provisional.get("hierarchy_contract_version")
        == "grid-feature-hierarchy-v2"
        and provisional.get("reference_commit")
        == GRID_RELEASE_COMMIT
        and provisional.get("authority_status") == "provisional_estimated",
        "Congestion provisional Grid contract drift",
    )
    require(
        "two_stage_authoritative" in metadata.get("aggregation_modes", []),
        "Congestion authoritative aggregation mode is missing",
    )
    require(
        "two_stage_provisional_estimated"
        in metadata.get("aggregation_modes", []),
        "Congestion provisional aggregation mode is missing",
    )

    layers = client.get_json("/models/congestion/layers")
    require(len(layers.get("layers", [])) == 1, "Congestion layer contract is missing")
    aggregate = layers["layers"][0]
    require(
        aggregate.get("id") == "transformer_profile_aggregates",
        "Congestion aggregate layer ID drift",
    )
    require(aggregate.get("resolution") == "PT15M", "Congestion layer resolution drift")
    require(
        aggregate.get("target_levels")
        == ["lv_mv_transformer", "mv_hv_transformer"],
        "Congestion target hierarchy drift",
    )


def check_transformer_profile_orchestration(client: SmokeClient) -> None:
    response = client.post_json(
        f"/policy-api/transformer-profiles/pc6/{ORCHESTRATION_PC6}",
        {
            "start": "2022-12-31T23:00:00Z",
            "end": "2023-01-01T00:00:00Z",
        },
        timeout=300,
        expected_status=200,
    )
    require(response.get("status") == "completed", "Transformer orchestration failed")
    require(
        response.get("grid_assignment", {}).get("hierarchy_policy")
        == "nearest_electrical_root_v1",
        "Grid hierarchy policy drift",
    )
    require(
        response.get("congestion_aggregation", {}).get("aggregation_mode")
        == "two_stage_provisional_estimated"
        and response.get("congestion_aggregation", {}).get("hierarchy_policy")
        == "nearest_electrical_root_v1",
        "Congestion orchestration authority drift",
    )
    require(
        response.get("feature", {}).get("source_feature_id") == ORCHESTRATION_PC6,
        "Transformer orchestration feature drift",
    )
    profile = response.get("profile", {})
    require(profile.get("model_id") == "consumption-map", "Profile model drift")
    require(profile.get("model_version") == "0.4.0", "Profile version drift")
    require(profile.get("resolution") == "PT15M", "Profile resolution drift")
    for field in ("layer_version", "profile_version"):
        value = profile.get(field)
        require(
            isinstance(value, str)
            and len(value) == 64
            and all(character in "0123456789abcdef" for character in value),
            f"Profile {field} is not an immutable SHA-256 identity",
        )

    result = response.get("result", {})
    require(
        result.get("aggregation_mode") == "two_stage_provisional_estimated",
        "Provisional aggregation mode drift",
    )
    require(result.get("persistence") == "none", "Scenario persistence drift")
    require(result.get("resolution") == "PT15M", "Aggregate resolution drift")
    require(result.get("complete") is True, "Transformer hierarchy is incomplete")
    require(
        isinstance(result.get("overall_datacompleetheid"), int)
        and not isinstance(result["overall_datacompleetheid"], bool)
        and 0 <= result["overall_datacompleetheid"] <= 1,
        "Aggregate datacompleetheid drift",
    )
    coverage = result.get("profile_coverage", [])
    require(len(coverage) == 1 and coverage[0].get("complete") is True, "Profile coverage drift")

    source_stage = result.get("source_to_lv_mv", {})
    target_stage = result.get("lv_mv_to_mv_hv", {})
    require(source_stage.get("complete") is True, "LV/MV aggregation is incomplete")
    require(target_stage.get("complete") is True, "MV/HV aggregation is incomplete")
    source_targets = source_stage.get("targets", [])
    target_targets = target_stage.get("targets", [])
    require(len(source_targets) == 3, "1483AA LV/MV transformer count drift")
    require(len(target_targets) == 1, "1483AA MV/HV transformer count drift")
    require(
        target_targets[0].get("transformer_id")
        == "grid-transformer-mv-hv-station-609006",
        "1483AA provisional parent is not OS OTERLEEK",
    )
    require(
        all(item.get("transformer_level") == "lv_mv_transformer" for item in source_targets),
        "LV/MV target level drift",
    )
    require(
        all(item.get("transformer_level") == "mv_hv_transformer" for item in target_targets),
        "MV/HV target level drift",
    )
    for target in [*source_targets, *target_targets]:
        points = target.get("points", [])
        require(len(points) == 4, "Transformer profile PT15M interval count drift")
        require(
            all(
                point.get("demand_power_kw", 0) > 0
                and point.get("production_power_kw") == 0
                and point.get("net_power_kw") == point.get("demand_power_kw")
                for point in points
            ),
            "Consumption-only transformer profile values drifted",
        )

    source_totals = [
        sum(target["points"][index]["net_power_kw"] for target in source_targets)
        for index in range(4)
    ]
    target_totals = [
        sum(target["points"][index]["net_power_kw"] for target in target_targets)
        for index in range(4)
    ]
    require(
        all(abs(source - target) <= 1e-9 for source, target in zip(source_totals, target_totals)),
        "LV/MV and MV/HV aggregate totals diverged",
    )
    require(
        len(result.get("hierarchy_resolutions", [])) == 3
        and all(
            item.get("status") == "available"
            and item.get("complete") is True
            and item.get("target_transformer_id")
            == "grid-transformer-mv-hv-station-609006"
            and item.get("datacompleetheid") == 1
            for item in result["hierarchy_resolutions"]
        ),
        "Grid hierarchy contains an unresolved transformer parent",
    )
    require(
        all(
            len(item.get("evidence", [])) == 1
            and item["evidence"][0].get("code")
            == "grid_lv_mv_to_mv_hv_hierarchy"
            and isinstance(item["evidence"][0].get("value"), dict)
            for item in result["hierarchy_resolutions"]
        ),
        "Grid provisional hierarchy evidence is missing",
    )
    hierarchy_evidence = [
        item["evidence"][0]["value"] for item in result["hierarchy_resolutions"]
    ]
    require(
        {item.get("electrical_distance_edges") for item in hierarchy_evidence}
        == {69, 72, 78}
        and all(
            item.get("hierarchy_policy_applied")
            == "nearest_electrical_root_v1"
            and item.get("hierarchy_authority_status") == "provisional_estimated"
            and item.get("evidence_status") == "model_estimated_provisional"
            and item.get("share_scope") == "provisional_lv_mv_to_mv_hv"
            and item.get("root_bus_ids") == ["27999"]
            and item.get("nearest_tied_root_bus_ids") == []
            for item in hierarchy_evidence
        ),
        "Grid provisional hierarchy evidence drift",
    )
    hierarchy_contributions = target_targets[0].get("hierarchy_contributions", [])
    require(
        len(hierarchy_contributions) == 3
        and all(
            item.get("relation_scope")
            == "provisional_estimated_electrical_parent"
            and item.get("relation_share") == 1.0
            and item.get("grid_model_git_sha")
            == GRID_RELEASE_COMMIT
            and item.get("hierarchy_datacompleetheid") == 1
            for item in hierarchy_contributions
        ),
        "Congestion provisional hierarchy contribution drift",
    )


def check_pv_transformer_profile_orchestration(
    client: SmokeClient, grid_data_mode: str
) -> None:
    response = client.post_json(
        f"/policy-api/transformer-profiles/pv/cbs-buurt/{PV_ORCHESTRATION_BUURT}",
        {
            "start": "2024-06-01T12:00:00Z",
            "end": "2024-06-01T13:00:00Z",
        },
        timeout=300,
        expected_status=200,
    )
    require(response.get("status") == "completed", "PV transformer orchestration failed")
    require(
        response.get("feature", {}).get("source_feature_id")
        == PV_ORCHESTRATION_BUURT,
        "PV transformer orchestration feature drift",
    )
    profile = response.get("profile", {})
    require(profile.get("model_id") == "pv-map", "PV profile model drift")
    require(profile.get("producer_model_id") == "pv-capacity-model", "PV producer drift")
    require(profile.get("model_version") == "0.3.0", "PV profile version drift")
    require(profile.get("profile_calendar") == 2024, "PV profile calendar drift")
    require(profile.get("scenario_year") == 2035, "PV scenario year drift")
    require(
        profile.get("canonical_sign_convention") == "negative_production",
        "PV canonical sign convention drift",
    )
    require(
        profile.get("release_commit") == PV_RELEASE_COMMIT
        and profile.get("container_image") == PV_CONTAINER_IMAGE,
        "PV orchestration release identity drift",
    )

    result = response.get("result", {})
    require(result.get("complete") is True, "PV transformer hierarchy is incomplete")
    require(
        result.get("aggregation_mode") == "two_stage_provisional_estimated",
        "PV provisional aggregation mode drift",
    )
    require(
        isinstance(result.get("overall_datacompleetheid"), int)
        and not isinstance(result["overall_datacompleetheid"], bool)
        and 0 <= result["overall_datacompleetheid"] <= 1,
        "PV aggregate datacompleetheid drift",
    )

    source_targets = result.get("source_to_lv_mv", {}).get("targets", [])
    target_targets = result.get("lv_mv_to_mv_hv", {}).get("targets", [])
    expected_lv_mv = (
        PV_ORCHESTRATION_FIXTURE_LV_MV
        if grid_data_mode == "fixture"
        else PV_ORCHESTRATION_REAL_LV_MV
    )
    require(
        {item.get("transformer_id") for item in source_targets} == expected_lv_mv,
        "PV LV/MV transformer set drift",
    )
    require(
        len(target_targets) == 1
        and target_targets[0].get("transformer_id") == PV_ORCHESTRATION_MV_HV,
        "PV MV/HV transformer target drift",
    )
    for target in [*source_targets, *target_targets]:
        points = target.get("points", [])
        require(len(points) == 4, "PV transformer PT15M interval count drift")
        require(
            all(
                point.get("demand_power_kw") == 0
                and point.get("production_power_kw", 0) < 0
                and point.get("net_power_kw") == point.get("production_power_kw")
                for point in points
            ),
            "PV transformer canonical production values drifted",
        )

    source_totals = [
        sum(target["points"][index]["net_power_kw"] for target in source_targets)
        for index in range(4)
    ]
    target_totals = [
        sum(target["points"][index]["net_power_kw"] for target in target_targets)
        for index in range(4)
    ]
    require(
        all(abs(source - target) <= 1e-9 for source, target in zip(source_totals, target_totals)),
        "PV LV/MV and MV/HV aggregate totals diverged",
    )
    require(all(value < 0 for value in target_totals), "PV daylight production is empty")

    hierarchy = result.get("hierarchy_resolutions", [])
    require(
        len(hierarchy) == 3
        and all(
            item.get("status") == "available"
            and item.get("complete") is True
            and item.get("target_transformer_id") == PV_ORCHESTRATION_MV_HV
            for item in hierarchy
        ),
        "PV hierarchy contains an unresolved transformer parent",
    )


def check_consumption_layer(client: SmokeClient) -> None:
    capabilities_query = urllib.parse.urlencode(
        {"service": "WMS", "version": "1.3.0", "request": "GetCapabilities"}
    )
    capabilities_path = f"/geoserver/wms?{capabilities_query}"
    deadline = time.monotonic() + 300
    while True:
        status, body, _ = client.get(capabilities_path)
        if status == 200 and CONSUMPTION_LAYER.encode() in body:
            break
        if time.monotonic() >= deadline:
            raise AssertionError("Consumption layer missing from WMS capabilities")
        time.sleep(5)

    describe_query = urllib.parse.urlencode(
        {
            "service": "WFS",
            "version": "2.0.0",
            "request": "DescribeFeatureType",
            "typeNames": CONSUMPTION_LAYER,
        }
    )
    status, body, _ = client.get(f"/geoserver/rdp/ows?{describe_query}")
    require(status == 200, "Consumption WFS DescribeFeatureType failed")
    for field in (
        "spatial_unit_type",
        "spatial_unit_code",
        "annual_electricity_consumption_kwh",
        "residential_electricity_kwh",
        "business_electricity_kwh",
        "datacompleetheid",
        "datacompleetheid_rule_version",
        "model_version",
    ):
        require(field.encode() in body, f"Consumption WFS schema is missing {field}")

    feature_query = urllib.parse.urlencode(
        {
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typeNames": CONSUMPTION_LAYER,
            "outputFormat": "application/json",
            "cql_filter": f"spatial_unit_code='{CONSUMPTION_FIXTURE}'",
        }
    )
    collection = client.get_json(f"/geoserver/rdp/ows?{feature_query}")
    require(collection.get("numberReturned") == 1, "Consumption fixture is missing")
    feature = collection["features"][0]
    properties = feature["properties"]
    require(properties["name"] == "Boekelermeer-Zuid", "Consumption fixture name drift")
    annual = properties["annual_electricity_consumption_kwh"]
    require(isinstance(annual, (int, float)) and annual > 0, "Consumption fixture is empty")
    require(0 <= properties["datacompleetheid"] <= 3, "Consumption quality drift")

    null_query = urllib.parse.urlencode(
        {
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typeNames": CONSUMPTION_LAYER,
            "outputFormat": "application/json",
            "cql_filter": "spatial_unit_code='BU03611000'",
        }
    )
    null_collection = client.get_json(f"/geoserver/rdp/ows?{null_query}")
    require(null_collection.get("numberReturned") == 1, "Consumption null fixture is missing")
    require(
        null_collection["features"][0]["properties"]["business_electricity_kwh"] is None,
        "Consumption null sector value was coerced",
    )

    coordinates = list(flatten_coordinates(feature["geometry"]["coordinates"]))
    xs = [coordinate[0] for coordinate in coordinates]
    ys = [coordinate[1] for coordinate in coordinates]
    padding = 0.001
    map_query = urllib.parse.urlencode(
        {
            "service": "WMS",
            "version": "1.1.1",
            "request": "GetMap",
            "layers": f"rdp:{CONSUMPTION_LAYER}",
            "styles": "",
            "srs": "EPSG:4326",
            "bbox": f"{min(xs)-padding},{min(ys)-padding},{max(xs)+padding},{max(ys)+padding}",
            "width": 256,
            "height": 256,
            "format": "image/png",
        }
    )
    status, image, content_type = client.get(f"/geoserver/rdp/wms?{map_query}")
    require(status == 200, "Consumption WMS GetMap failed")
    require(content_type == "image/png", f"Unexpected Consumption WMS type: {content_type}")
    require(
        image.startswith(b"\x89PNG") and len(image) > 1000,
        "Consumption WMS map is empty",
    )


def check_dashboard_and_simulation(client: SmokeClient) -> None:
    status, dashboard, _ = client.get("/dashboard/")
    require(status == 200, "Dashboard did not load")
    require(b"map-data.js" in dashboard, "Dashboard does not load its map data adapter")
    require(b"r-pv-capacity" in dashboard, "Dashboard PV layer control is missing")
    require(b"r-ev-chargers" in dashboard, "Dashboard EV layer control is missing")
    require(b"r-grid-network" in dashboard, "Dashboard Grid control is missing")
    for control_id in (
        b"grid-lv-lines", b"grid-mv-lines", b"grid-hv-lines",
        b"grid-lv-mv-transformers", b"grid-mv-hv-transformers",
        b"grid-lv-mv-reach", b"grid-mv-hv-reach",
    ):
        require(control_id in dashboard, f"Dashboard Grid visibility control is missing: {control_id!r}")
    require(b"r-wind-turbines" in dashboard, "Dashboard Wind layer control is missing")
    require(b"r-heat-network" in dashboard, "Dashboard Heat model control is missing")
    require(b"heat-visibility" in dashboard, "Dashboard Heat visibility controls are missing")
    require(b"heat-evidence-summary" in dashboard, "Dashboard Heat evidence summary is missing")
    require(
        b"heat-visualization.js" in dashboard,
        "Dashboard does not load its Heat visualization adapter",
    )
    for layer_id in HEAT_LAYERS:
        require(layer_id.encode() in dashboard, f"Dashboard {layer_id} control is missing")
    for view_id, checked in HEAT_VIEWS.items():
        marker = f'data-heat-view="{view_id}"'.encode()
        require(marker in dashboard, f"Dashboard Heat view is missing: {view_id}")
        control = dashboard.split(marker, 1)[1].split(b">", 1)[0]
        require(
            (b" checked" in control) is checked,
            f"Dashboard Heat view default drift: {view_id}",
        )
    require(b"scenario-panel" in dashboard, "Persistent scenario controls are missing")

    status, script, _ = client.get("/dashboard/map-data.js")
    require(status == 200, "Map data adapter did not load")
    require(b"policy_tool_pc6_energy" in script, "Dashboard is not configured for PC6 WFS")
    require(b"pv_capacity" in script, "Dashboard is not configured for PV WFS")
    require(b"public_ev_chargers" in script, "Dashboard is not configured for EV WFS")
    require(b"grid_lines" in script, "Dashboard is not configured for grid lines WFS")
    require(b"grid_transformers" in script, "Dashboard is not configured for transformers WFS")
    require(b"grid_mv_hv_transformer_reach" in script, "Dashboard is not configured for MV/HV reach WFS")
    require(b"grid_lv_mv_transformer_reach" in script, "Dashboard is not configured for LV/MV reach WFS")
    require(b"public_wind_turbines" in script, "Dashboard is not configured for Wind WFS")
    require(
        b"consumption_electricity_areas" in script,
        "Dashboard is not configured for Consumption WFS",
    )
    for layer_id in HEAT_LAYERS:
        require(layer_id.encode() in script, f"Dashboard is not configured for {layer_id}")
    require(b"alkmaar_energy_map.geojson" in script, "Static fallback is missing")

    status, heat_visualization, _ = client.get("/dashboard/heat-visualization.js")
    require(status == 200, "Heat visualization adapter did not load")
    for evidence_field in (
        b"reported_connected_share_pct",
        b"inference_class",
        b"allocated_connected_dwellings_est",
        b"liander_crosscheck_status",
        b"unallocated_pc6_heat_signals",
        b"excluded_electric_heating_pc6",
    ):
        require(
            evidence_field in heat_visualization,
            f"Heat visualization does not use evidence field {evidence_field!r}",
        )

    api = client.get_json("/policy-api/")
    require(api.get("message") == "Policy Tool API is active", "Policy API is unhealthy")
    registry = client.get_json("/policy-api/layers")
    records = {record["local_id"]: record for record in registry.get("layers", [])}
    require("layer:policy-tool:pc6-energy" in records, "PC6 registry record is missing")
    require("layer:pv-map:capacity" in records, "PV registry record is missing")
    require("layer:ev-map:public-chargers" in records, "EV registry record is missing")
    require(
        "layer:consumption-map:electricity-areas" in records,
        "Consumption registry record is missing",
    )
    require("layer:grid-model:lines" in records, "Grid lines registry record is missing")
    require(
        "layer:grid-model:transformers" in records,
        "Grid transformers registry record is missing",
    )
    require(
        "layer:grid-model:lv-mv-transformer-reach" in records,
        "Grid LV/MV reach registry record is missing",
    )
    require(
        "layer:grid-model:mv-hv-transformer-reach" in records,
        "Grid MV/HV reach registry record is missing",
    )
    require(
        "layer:wind-turbine-map:public-turbines" in records,
        "Wind registry record is missing",
    )
    for layer_id in HEAT_LAYERS:
        require(f"layer:heat-net-map:{layer_id}" in records, f"{layer_id} registry record is missing")
    for local_id, qualified_layer in (
        ("layer:grid-model:lines", "rdp:grid_lines"),
        ("layer:grid-model:transformers", "rdp:grid_transformers"),
        ("layer:grid-model:mv-hv-transformer-reach", "rdp:grid_mv_hv_transformer_reach"),
        ("layer:grid-model:lv-mv-transformer-reach", "rdp:grid_lv_mv_transformer_reach"),
    ):
        record = records[local_id]
        require(record["model_version"] == "2.1.0", f"{local_id} version drift")
        require(record["services"]["qualified_layer"] == qualified_layer, f"{local_id} layer drift")
    pv_record = records["layer:pv-map:capacity"]
    require(pv_record["model_version"] == "0.3.0", "PV registry version drift")
    require(pv_record["crs"] == "EPSG:4326", "PV registry CRS drift")
    require(
        pv_record["data_quality"]["method_version"]
        == "pv-datacompleetheid/1.0.0",
        "PV registry quality method drift",
    )
    require(
        pv_record["services"]["qualified_layer"] == "rdp:pv_capacity",
        "PV registry GeoServer layer drift",
    )
    ev_record = records["layer:ev-map:public-chargers"]
    require(ev_record["model_version"] == "0.3.0", "EV registry version drift")
    require(ev_record["crs"] == "EPSG:4326", "EV registry CRS drift")
    require(
        ev_record["data_quality"]["method_version"] == "EV-DATA-COMPLETE-001",
        "EV registry quality method drift",
    )
    require(
        ev_record["services"]["qualified_layer"] == "rdp:public_ev_chargers",
        "EV registry GeoServer layer drift",
    )
    consumption_record = records["layer:consumption-map:electricity-areas"]
    require(
        consumption_record["model_version"] == "0.4.0",
        "Consumption registry version drift",
    )
    require(
        consumption_record["crs"] == "EPSG:4326",
        "Consumption registry CRS drift",
    )
    require(
        consumption_record["data_quality"]["method_version"]
        == "datacompleetheid-qualitative-v1",
        "Consumption registry quality method drift",
    )
    require(
        consumption_record["services"]["qualified_layer"]
        == "rdp:consumption_electricity_areas",
        "Consumption registry GeoServer layer drift",
    )
    wind_record = records["layer:wind-turbine-map:public-turbines"]
    require(wind_record["model_version"] == "0.2.0", "Wind registry version drift")
    require(wind_record["crs"] == "EPSG:4326", "Wind registry CRS drift")
    require(
        wind_record["data_quality"]["method_version"] == "WIND-DATA-COMPLETE-001",
        "Wind registry quality method drift",
    )
    require(
        wind_record["services"]["qualified_layer"] == "rdp:public_wind_turbines",
        "Wind registry GeoServer layer drift",
    )
    for layer_id in HEAT_LAYERS:
        record = records[f"layer:heat-net-map:{layer_id}"]
        require(record["model_version"] == "0.2.0", f"{layer_id} registry version drift")
        require(record["crs"] == "EPSG:4326", f"{layer_id} registry CRS drift")
        require(
            record["data_quality"]["method_version"] == HEAT_QUALITY_METHOD,
            f"{layer_id} registry quality method drift",
        )
        require(
            record["services"]["qualified_layer"] == f"rdp:{layer_id}",
            f"{layer_id} registry GeoServer layer drift",
        )

    simulation = client.get_json(
        f"/policy-api/simulate/{FIXTURE}?electrification=0", timeout=300
    )
    require(simulation.get("status") == "success", "PC6 simulation failed")
    status, csv_body, _ = client.get(simulation["url"], timeout=60)
    require(status == 200, "Generated profile CSV was not served")
    rows = list(csv.reader(io.StringIO(csv_body.decode("utf-8"))))
    require(len(rows) > 100, "Generated profile CSV is unexpectedly short")
    require(
        rows[0]
        == [
            "timestamp",
            "electrical_demand_gross_kwh",
            "pv_generation_kwh",
            "electrical_demand_net_kwh",
            "heat_demand_kwh_th",
            "hp_electricity_input_kwh",
            "gas_input_kwh",
        ],
        "Generated profile CSV schema changed",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1")
    parser.add_argument(
        "--host-header",
        help="Optional HTTP Host header for smoke clients running inside Compose.",
    )
    parser.add_argument(
        "--expected-grid-data-mode",
        choices=("real_source", "fixture"),
        default="real_source",
    )
    args = parser.parse_args()

    client = SmokeClient(args.base_url, host_header=args.host_header)
    wait_until_ready(client, "/dashboard/")
    wait_until_ready(client, "/policy-api/")
    wait_until_ready(client, "/models/pv/ready", timeout=1800)
    wait_until_ready(client, "/models/grid/ready", timeout=300)
    wait_until_ready(client, "/models/wind/ready", timeout=300)
    wait_until_ready(client, "/models/heat/ready", timeout=300)
    wait_until_ready(client, "/models/ev/ready", timeout=300)
    wait_until_ready(client, "/models/consumption/readyz", timeout=300)
    wait_until_ready(client, "/models/congestion/ready", timeout=300)
    wait_until_ready(
        client, "/geoserver/wms?service=WMS&version=1.3.0&request=GetCapabilities"
    )
    # Publication runs the same heavyweight capacity calculation. Wait for it
    # before starting the independent API run so acceptance never overlaps two
    # full PV calculations on a small CI runner.
    check_pv_layer(client)
    check_pv_model_api(client)
    check_grid_model_api(client, args.expected_grid_data_mode)
    check_wind_model_api(client)
    check_heat_model_api(client)
    check_ev_model_api(client)
    check_consumption_model_api(client)
    check_congestion_model_api(client)
    check_pc6_layer(client)
    check_grid_layers(client)
    check_wind_layer(client)
    check_heat_layers(client)
    check_ev_layer(client)
    check_consumption_layer(client)
    check_transformer_profile_orchestration(client)
    check_pv_transformer_profile_orchestration(client, args.expected_grid_data_mode)
    check_dashboard_and_simulation(client)
    print(
        "Integrated PC6, PV capacity and transformer profiles, Grid, Wind, "
        "Heat, EV, Consumption, and Congestion smoke test passed"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Smoke test failed: {exc}", file=sys.stderr)
        raise
