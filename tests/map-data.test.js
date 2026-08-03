const assert = require('node:assert/strict');
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

test('rejects empty feature collections', () => {
    assert.throws(
        () => mapData.validateFeatureCollection(
            { type: 'FeatureCollection', features: [] },
            'test source'
        ),
        /non-empty/
    );
});
