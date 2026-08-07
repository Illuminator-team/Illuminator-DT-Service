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
PV_FIXTURE = "BU03610302"
PV_RELEASE_COMMIT = "bd29351e108d9db002b9e54d5c7fb2356416a306"
PV_CONTAINER_IMAGE = "ghcr.io/jortgroen/pv-map-api@sha256:0fffb8dd6e725956257c4dc51c94225ea7c5745478ed33cf8bce597ee8551710"
GRID_RELEASE_COMMIT = "36bfcfbdca4030068a2ec1e2677bf2b334bb4a46"
GRID_CONTAINER_DIGEST = "sha256:ed241d2dc64de8f9cb21a56595f58725bac4cdf91932f5623d4e20b9867a83c2"
GRID_BBOX = [4.774287, 52.629131, 4.779526, 52.635583]
GRID_TRANSFORMER_FIXTURE = "grid-transformer-trafo_MV_LV_1157"
FIXTURE = "1842EM"


class SmokeClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=context)
        )

    def get(self, path: str, timeout: int = 60) -> tuple[int, bytes, str]:
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            headers={"Accept": "*/*", "User-Agent": "rdp-integration-smoke/1.0"},
        )
        with self.opener.open(request, timeout=timeout) as response:
            return response.status, response.read(), response.headers.get_content_type()

    def get_json(self, path: str, timeout: int = 60) -> dict:
        status, body, _ = self.get(path, timeout=timeout)
        if status != 200:
            raise AssertionError(f"{path} returned HTTP {status}")
        return json.loads(body)

    def post_json(self, path: str, payload: dict, timeout: int = 60) -> dict:
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            method="POST",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "rdp-integration-smoke/1.0",
            },
        )
        with self.opener.open(request, timeout=timeout) as response:
            require(response.status == 201, f"{path} returned HTTP {response.status}")
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
    require(len(layers.get("layers", [])) == 1, "PV layer contract is missing")
    require(layers["layers"][0]["layer_id"] == PV_LAYER, "PV layer ID drift")

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


def check_grid_model_api(client: SmokeClient) -> None:
    root = client.get_json("/models/grid/")
    require(root.get("status") == "alive", "Grid model liveness failed")

    readiness = client.get_json("/models/grid/ready", timeout=120)
    require(readiness.get("status") == "ready", "Grid model is not ready")
    require(readiness.get("data_mode") == "fixture", "Grid fixture mode drift")
    grid_data_version = readiness.get("grid_data_version")
    require(
        isinstance(grid_data_version, str) and grid_data_version.startswith("grid-"),
        "Grid data version is missing",
    )

    metadata = client.get_json("/models/grid/metadata")
    release = metadata.get("release", {})
    require(
        release.get("git_commit") == GRID_RELEASE_COMMIT,
        "Grid release identity drift",
    )
    require(
        release.get("container_digest") == GRID_CONTAINER_DIGEST,
        "Grid image identity drift",
    )
    require(
        metadata.get("active_grid_data", {}).get("data_mode") == "fixture",
        "Grid metadata data mode drift",
    )

    layers = client.get_json("/models/grid/layers")
    by_layer = {item["id"]: item for item in layers.get("layers", [])}
    require(
        set(by_layer) == {GRID_LINES_LAYER, GRID_TRANSFORMERS_LAYER},
        "Grid layer contract drift",
    )
    require(
        by_layer[GRID_LINES_LAYER]["runtime"]["feature_count"] == 22,
        "Grid line fixture count drift",
    )
    require(
        by_layer[GRID_TRANSFORMERS_LAYER]["runtime"]["feature_count"] == 1,
        "Grid transformer fixture count drift",
    )

    run = client.post_json(
        "/models/grid/runs",
        {
            "operation": "export_layers",
            "selection": {"type": "bbox", "bbox": GRID_BBOX},
            "layer_ids": [GRID_LINES_LAYER, GRID_TRANSFORMERS_LAYER],
            "voltage_levels": [],
            "component_ids": [],
        },
        timeout=300,
    )
    require(run.get("status") == "completed", "Grid export run failed")
    outputs = {item["layer_id"]: item for item in run.get("outputs", [])}
    require(outputs[GRID_LINES_LAYER]["feature_count"] == 22, "Grid line export drift")
    require(
        outputs[GRID_TRANSFORMERS_LAYER]["feature_count"] == 1,
        "Grid transformer export drift",
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
    require(
        assignment.get("serving_transformer_id") == GRID_TRANSFORMER_FIXTURE,
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


def check_dashboard_and_simulation(client: SmokeClient) -> None:
    status, dashboard, _ = client.get("/dashboard/")
    require(status == 200, "Dashboard did not load")
    require(b"map-data.js" in dashboard, "Dashboard does not load its map data adapter")
    require(b"r-pv-capacity" in dashboard, "Dashboard PV layer control is missing")
    require(b"r-grid-lines" in dashboard, "Dashboard grid lines control is missing")
    require(b"r-grid-transformers" in dashboard, "Dashboard grid transformers control is missing")
    require(b"scenario-panel" in dashboard, "Persistent scenario controls are missing")

    status, script, _ = client.get("/dashboard/map-data.js")
    require(status == 200, "Map data adapter did not load")
    require(b"policy_tool_pc6_energy" in script, "Dashboard is not configured for PC6 WFS")
    require(b"pv_capacity" in script, "Dashboard is not configured for PV WFS")
    require(b"grid_lines" in script, "Dashboard is not configured for grid lines WFS")
    require(b"grid_transformers" in script, "Dashboard is not configured for transformers WFS")
    require(b"alkmaar_energy_map.geojson" in script, "Static fallback is missing")

    api = client.get_json("/policy-api/")
    require(api.get("message") == "Policy Tool API is active", "Policy API is unhealthy")
    registry = client.get_json("/policy-api/layers")
    records = {record["local_id"]: record for record in registry.get("layers", [])}
    require("layer:policy-tool:pc6-energy" in records, "PC6 registry record is missing")
    require("layer:pv-map:capacity" in records, "PV registry record is missing")
    require("layer:grid-model:lines" in records, "Grid lines registry record is missing")
    require(
        "layer:grid-model:transformers" in records,
        "Grid transformers registry record is missing",
    )
    for local_id, qualified_layer in (
        ("layer:grid-model:lines", "rdp:grid_lines"),
        ("layer:grid-model:transformers", "rdp:grid_transformers"),
    ):
        record = records[local_id]
        require(record["model_version"] == "1.0.0", f"{local_id} version drift")
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
    parser.add_argument("--base-url", default="https://localhost")
    args = parser.parse_args()

    client = SmokeClient(args.base_url)
    wait_until_ready(client, "/dashboard/")
    wait_until_ready(client, "/policy-api/")
    wait_until_ready(client, "/models/pv/ready", timeout=1800)
    wait_until_ready(client, "/models/grid/ready", timeout=300)
    wait_until_ready(
        client, "/geoserver/wms?service=WMS&version=1.3.0&request=GetCapabilities"
    )
    check_pv_model_api(client)
    check_grid_model_api(client)
    check_pc6_layer(client)
    check_pv_layer(client)
    check_grid_layers(client)
    check_dashboard_and_simulation(client)
    print("Integrated PC6, PV capacity, and grid layer smoke test passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Smoke test failed: {exc}", file=sys.stderr)
        raise
