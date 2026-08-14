const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const mapData = require('../policy-tool-frontend/map-data.js');

function response(ok, status, payload) {
    return {
        ok,
        status,
        async json() {
            return payload;
        }
    };
}

function collection(properties = {}) {
    return {
        type: 'FeatureCollection',
        features: [{
            type: 'Feature',
            properties: { postcode6: '1842EM', ...properties },
            geometry: { type: 'MultiPolygon', coordinates: [] }
        }]
    };
}

test('uses GeoServer WFS as the primary PC6 source', async () => {
    const calls = [];
    const fetchImpl = async (url) => {
        calls.push(url);
        return response(true, 200, collection({ datacompleetheid: 2 }));
    };

    const result = await mapData.loadPc6FeatureCollection(fetchImpl);

    assert.equal(result.source, 'geoserver_wfs');
    assert.equal(result.fallbackReason, null);
    assert.deepEqual(calls, [mapData.WFS_URL]);
});

test('falls back to the checked-in GeoJSON and adds quality metadata', async () => {
    const calls = [];
    const fetchImpl = async (url) => {
        calls.push(url);
        if (url === mapData.WFS_URL) {
            return response(false, 503, {});
        }
        return response(true, 200, collection());
    };

    const result = await mapData.loadPc6FeatureCollection(fetchImpl);
    const properties = result.data.features[0].properties;

    assert.equal(result.source, 'static_geojson');
    assert.match(result.fallbackReason, /HTTP 503/);
    assert.deepEqual(calls, [mapData.WFS_URL, mapData.FALLBACK_URL]);
    assert.equal(properties.datacompleetheid, 2);
    assert.equal(properties.datacompleetheid_label, 'redelijke betrouwbaarheid');
    assert.equal(
        properties.datacompleetheid_method,
        'legacy-pc6-layer-qualitative-v1'
    );
});

test('loads PV capacity as an independent GeoServer WFS layer', async () => {
    const calls = [];
    const payload = collection({
        cbs_buurt_code: 'BU03610302',
        buurt_name: 'Overdie-Oost',
        pv_capacity_kwp: 42.5,
        datacompleetheid: 2
    });
    const fetchImpl = async (url) => {
        calls.push(url);
        return response(true, 200, payload);
    };

    const result = await mapData.loadPvFeatureCollection(fetchImpl);

    assert.equal(result.source, 'geoserver_wfs');
    assert.equal(result.data.features[0].properties.pv_capacity_kwp, 42.5);
    assert.deepEqual(calls, [mapData.PV_WFS_URL]);
});

test('does not substitute consumption GeoJSON when PV WFS fails', async () => {
    await assert.rejects(
        () => mapData.loadPvFeatureCollection(async () => response(false, 503, {})),
        /HTTP 503/
    );
});

test('rejects empty feature collections', () => {
    assert.throws(
        () => mapData.validateFeatureCollection(
            { type: 'FeatureCollection', features: [] },
            'test source'
        ),
        /non-empty/
    );
});

test('keeps congestion controls outside layer-specific details', () => {
    const frontendDirectory = path.join(__dirname, '..', 'policy-tool-frontend');
    const html = fs.readFileSync(path.join(frontendDirectory, 'index.html'), 'utf8');
    const script = fs.readFileSync(path.join(frontendDirectory, 'script.js'), 'utf8');
    const featurePanelMatch = html.match(
        /<section id="feature-panel"[\s\S]*?<\/section>/
    );
    const scenarioPanelMatch = html.match(
        /<section id="scenario-panel"[\s\S]*?<\/section>/
    );
    const featurePanel = featurePanelMatch && featurePanelMatch[0];
    const scenarioPanel = scenarioPanelMatch && scenarioPanelMatch[0];

    assert.ok(featurePanel, 'feature panel is present');
    assert.ok(scenarioPanel, 'scenario panel is present');
    assert.doesNotMatch(featurePanel, /id="run-sim-btn"/);
    assert.match(scenarioPanel, /id="input-gas"/);
    assert.match(scenarioPanel, /id="input-pv"/);
    assert.match(scenarioPanel, /id="run-sim-btn"/);
    assert.match(scenarioPanel, /id="simulation-output"/);
    assert.equal((html.match(/id="run-sim-btn"/g) || []).length, 1);
    assert.doesNotMatch(script, /id="run-sim-btn"/);
    assert.match(script, /function initializeScenarioControls\(\)/);
    assert.match(script, /function updatePvSidePanel\(prop\)/);
    assert.match(script, /function updateConsumptionSidePanel\(prop\)/);
});

test('loads grid lines, transformers, and both PC6 reach maps as independent GeoServer layers', async () => {
    const calls = [];
    const payload = collection({
        component_id: 'grid-line-test',
        datacompleetheid: 2
    });
    const fetchImpl = async (url) => {
        calls.push(url);
        return response(true, 200, payload);
    };

    const lines = await mapData.loadGridLinesFeatureCollection(fetchImpl);
    const transformers = await mapData.loadGridTransformersFeatureCollection(fetchImpl);
    const lvMvReach = await mapData.loadGridLvMvReachFeatureCollection(fetchImpl);
    const reach = await mapData.loadGridMvHvReachFeatureCollection(fetchImpl);

    assert.equal(lines.source, 'geoserver_wfs');
    assert.equal(transformers.source, 'geoserver_wfs');
    assert.equal(reach.source, 'geoserver_wfs');
    assert.equal(lvMvReach.source, 'geoserver_wfs');
    assert.deepEqual(calls, [
        mapData.GRID_LINES_WFS_URL,
        mapData.GRID_TRANSFORMERS_WFS_URL,
        mapData.GRID_LV_MV_REACH_WFS_URL,
        mapData.GRID_MV_HV_REACH_WFS_URL
    ]);
});

test('does not substitute another layer when a grid WFS request fails', async () => {
    await assert.rejects(
        () => mapData.loadGridLinesFeatureCollection(
            async () => response(false, 503, {})
        ),
        /HTTP 503/
    );
});

test('loads public EV chargers as an independent GeoServer layer', async () => {
    const calls = [];
    const payload = collection({
        feature_id: 'ev-charger-NL-ALL-NLLOC018787',
        address: 'Diamantweg 10',
        connector_count: 6,
        datacompleetheid: 2
    });
    const result = await mapData.loadEvChargersFeatureCollection(async (url) => {
        calls.push(url);
        return response(true, 200, payload);
    });

    assert.equal(result.source, 'geoserver_wfs');
    assert.equal(result.data.features[0].properties.connector_count, 6);
    assert.deepEqual(calls, [mapData.EV_CHARGERS_WFS_URL]);
});

test('does not substitute another layer when EV WFS fails', async () => {
    await assert.rejects(
        () => mapData.loadEvChargersFeatureCollection(
            async () => response(false, 503, {})
        ),
        /HTTP 503/
    );
});

test('loads Consumption areas as an independent GeoServer layer', async () => {
    const calls = [];
    const payload = collection({
        feature_id: 'consumption-area-BU03610308',
        spatial_unit_code: 'BU03610308',
        annual_electricity_consumption_kwh: 12500000,
        datacompleetheid: 2
    });
    const result = await mapData.loadConsumptionAreasFeatureCollection(async (url) => {
        calls.push(url);
        return response(true, 200, payload);
    });

    assert.equal(result.source, 'geoserver_wfs');
    assert.equal(
        result.data.features[0].properties.annual_electricity_consumption_kwh,
        12500000
    );
    assert.deepEqual(calls, [mapData.CONSUMPTION_AREAS_WFS_URL]);
});

test('does not substitute another layer when Consumption WFS fails', async () => {
    await assert.rejects(
        () => mapData.loadConsumptionAreasFeatureCollection(
            async () => response(false, 503, {})
        ),
        /HTTP 503/
    );
});

test('loads Wind turbines as an independent GeoServer point layer', async () => {
    const calls = [];
    const payload = {
        type: 'FeatureCollection',
        features: [{
            type: 'Feature',
            id: 'wind-turbine-2811',
            properties: {
                feature_id: 'wind-turbine-2811',
                capacity_kw: 2050,
                datacompleetheid: 2
            },
            geometry: { type: 'Point', coordinates: [4.7523, 52.593] }
        }]
    };
    const fetchImpl = async (url) => {
        calls.push(url);
        return response(true, 200, payload);
    };

    const result = await mapData.loadWindTurbinesFeatureCollection(fetchImpl);

    assert.equal(result.source, 'geoserver_wfs');
    assert.equal(result.data.features[0].properties.capacity_kw, 2050);
    assert.deepEqual(calls, [mapData.WIND_TURBINES_WFS_URL]);
});

test('does not substitute another layer when Wind WFS fails', async () => {
    await assert.rejects(
        () => mapData.loadWindTurbinesFeatureCollection(
            async () => response(false, 503, {})
        ),
        /HTTP 503/
    );
});

test('loads every Heat evidence layer from its independent GeoServer WFS URL', async () => {
    const calls = [];
    const fetchImpl = async (url) => {
        calls.push(url);
        return response(true, 200, collection({
            feature_id: 'fixture-heat-feature',
            datacompleetheid: 2
        }));
    };

    for (const layerId of mapData.HEAT_LAYER_IDS) {
        const result = await mapData.loadHeatFeatureCollection(fetchImpl, layerId);
        assert.equal(result.source, 'geoserver_wfs');
    }

    assert.deepEqual(
        calls,
        mapData.HEAT_LAYER_IDS.map((layerId) => mapData.HEAT_WFS_URLS[layerId])
    );
});

test('accepts an empty Heat layer but never substitutes another model layer', async () => {
    const empty = { type: 'FeatureCollection', features: [] };
    const result = await mapData.loadHeatFeatureCollection(
        async () => response(true, 200, empty),
        'registered_heat_network_developments'
    );
    assert.equal(result.data.features.length, 0);

    await assert.rejects(
        () => mapData.loadHeatFeatureCollection(
            async () => response(false, 503, {}),
            'potential_heat_sources'
        ),
        /HTTP 503/
    );
    await assert.rejects(
        () => mapData.loadHeatFeatureCollection(async () => response(true, 200, empty), 'other'),
        /Unknown Heat layer/
    );
});

test('grid details leave the persistent congestion controls in place', () => {
    const frontendDirectory = path.join(__dirname, '..', 'policy-tool-frontend');
    const html = fs.readFileSync(path.join(frontendDirectory, 'index.html'), 'utf8');
    const script = fs.readFileSync(path.join(frontendDirectory, 'script.js'), 'utf8');

    assert.match(html, /id="r-grid-network"/);
    assert.match(html, /id="grid-lv-lines"/);
    assert.match(html, /id="grid-mv-lines"/);
    assert.match(html, /id="grid-hv-lines"/);
    assert.match(html, /id="grid-lv-mv-transformers"/);
    assert.match(html, /id="grid-mv-hv-transformers"/);
    assert.match(html, /id="grid-lv-mv-reach"/);
    assert.match(html, /id="grid-mv-hv-reach"/);
    assert.match(script, /function updateGridLineSidePanel\(prop\)/);
    assert.match(script, /function updateGridTransformerSidePanel\(prop\)/);
    assert.match(script, /function updateGridReachSidePanel\(prop, level\)/);
    assert.match(script, /ranked_shares_json/);
    assert.doesNotMatch(script, /COARSE MODEL-ESTIMATED REACH/);
    assert.match(script, /function selectScenarioTargetByPc6\(pc6Id\)/);
    assert.match(script, /updateGridReachSidePanel[\s\S]{0,250}selectScenarioTargetByPc6/);
    assert.match(script, /function applyGridVisibility\(fit = false\)/);
    assert.match(html, /id="r-wind-turbines"/);
    assert.match(html, /id="r-ev-chargers"/);
    assert.match(html, /id="heat-layer-select"/);
    mapData.HEAT_LAYER_IDS.forEach((layerId) => assert.match(html, new RegExp(layerId)));
    assert.match(script, /function updateGridLineSidePanel\(prop\)/);
    assert.match(script, /function updateGridTransformerSidePanel\(prop\)/);
    assert.match(script, /function updateWindTurbineSidePanel\(prop\)/);
    assert.match(script, /function updateEvSidePanel\(prop\)/);
    assert.match(script, /function updateHeatSidePanel\(layerId, prop\)/);
    assert.equal((html.match(/id="run-sim-btn"/g) || []).length, 1);
    assert.doesNotMatch(script, /updateGridLineSidePanel[\s\S]{0,200}selectScenarioTarget/);
});
