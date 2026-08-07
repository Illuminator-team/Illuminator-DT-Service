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
});

test('loads grid lines and transformers as independent GeoServer layers', async () => {
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

    assert.equal(lines.source, 'geoserver_wfs');
    assert.equal(transformers.source, 'geoserver_wfs');
    assert.deepEqual(calls, [
        mapData.GRID_LINES_WFS_URL,
        mapData.GRID_TRANSFORMERS_WFS_URL
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

test('grid details leave the persistent congestion controls in place', () => {
    const frontendDirectory = path.join(__dirname, '..', 'policy-tool-frontend');
    const html = fs.readFileSync(path.join(frontendDirectory, 'index.html'), 'utf8');
    const script = fs.readFileSync(path.join(frontendDirectory, 'script.js'), 'utf8');

    assert.match(html, /id="r-grid-lines"/);
    assert.match(html, /id="r-grid-transformers"/);
    assert.match(script, /function updateGridLineSidePanel\(prop\)/);
    assert.match(script, /function updateGridTransformerSidePanel\(prop\)/);
    assert.equal((html.match(/id="run-sim-btn"/g) || []).length, 1);
    assert.doesNotMatch(script, /updateGridLineSidePanel[\s\S]{0,200}selectScenarioTarget/);
});
