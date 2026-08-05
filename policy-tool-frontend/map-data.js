(function (root, factory) {
    const api = factory();
    if (typeof module === 'object' && module.exports) {
        module.exports = api;
    }
    root.Pc6MapData = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    const WFS_URL = '/geoserver/rdp/ows?service=WFS&version=2.0.0&request=GetFeature&typeNames=policy_tool_pc6_energy&outputFormat=application%2Fjson&srsName=EPSG%3A4326';
    const PV_WFS_URL = '/geoserver/rdp/ows?service=WFS&version=2.0.0&request=GetFeature&typeNames=pv_capacity&outputFormat=application%2Fjson&srsName=EPSG%3A4326';
    const FALLBACK_URL = 'data/alkmaar_energy_map.geojson';
    const FALLBACK_QUALITY = Object.freeze({
        datacompleetheid: 2,
        datacompleetheid_label: 'redelijke betrouwbaarheid',
        datacompleetheid_method: 'legacy-pc6-layer-qualitative-v1',
        evidence_summary: 'Combines real/open annual energy and building data with standard load profiles, enrichment, estimates, and assumptions.'
    });

    function validateFeatureCollection(data, source) {
        if (!data || data.type !== 'FeatureCollection' || !Array.isArray(data.features) || data.features.length === 0) {
            throw new Error(`${source} did not return a non-empty GeoJSON FeatureCollection`);
        }
        return data;
    }

    async function fetchCollection(fetchImpl, url, source) {
        const response = await fetchImpl(url, { headers: { Accept: 'application/geo+json, application/json' } });
        if (!response.ok) {
            throw new Error(`${source} returned HTTP ${response.status}`);
        }
        return validateFeatureCollection(await response.json(), source);
    }

    function addFallbackQuality(data) {
        data.features.forEach((feature) => {
            feature.properties = feature.properties || {};
            Object.entries(FALLBACK_QUALITY).forEach(([key, value]) => {
                if (feature.properties[key] === undefined || feature.properties[key] === null) {
                    feature.properties[key] = value;
                }
            });
        });
        return data;
    }

    async function loadPc6FeatureCollection(fetchImpl) {
        try {
            const data = await fetchCollection(fetchImpl, WFS_URL, 'GeoServer WFS');
            return { data, source: 'geoserver_wfs', fallbackReason: null };
        } catch (wfsError) {
            const fallback = await fetchCollection(fetchImpl, FALLBACK_URL, 'Static GeoJSON fallback');
            return {
                data: addFallbackQuality(fallback),
                source: 'static_geojson',
                fallbackReason: wfsError.message
            };
        }
    }

    async function loadPvFeatureCollection(fetchImpl) {
        const data = await fetchCollection(fetchImpl, PV_WFS_URL, 'PV capacity GeoServer WFS');
        return { data, source: 'geoserver_wfs', fallbackReason: null };
    }

    return {
        FALLBACK_QUALITY,
        FALLBACK_URL,
        PV_WFS_URL,
        WFS_URL,
        addFallbackQuality,
        loadPc6FeatureCollection,
        loadPvFeatureCollection,
        validateFeatureCollection
    };
}));
