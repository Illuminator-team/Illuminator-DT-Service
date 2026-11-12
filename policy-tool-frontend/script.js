// Initialize Map
const map = L.map('map', { zoomControl: false }).setView([52.632, 4.753], 13);

L.control.zoom({ position: 'bottomleft' }).addTo(map);

// Add Base Layer
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '© OpenStreetMap',
    opacity: 0.85
}).addTo(map);

let pc6Layer;
let pvLayer;
let gridMvLinesLayer;
let gridCapacityLayer;
let gridHasFit = false;
let windTurbinesLayer;
let evChargersLayer;
let consumptionAreasLayer;
const heatMapLayers = {};
const heatFeatureCollections = {};
let heatHasFit = false;
let currentMetric = 'gas';
let pc6LayerSource = 'loading';
let pvLayerSource = 'loading';
const gridLayerSources = {
    grid_mv_lines: 'loading',
    grid_capacity_limits: 'loading'
};
const gridCanvasRenderer = L.canvas({ padding: 0.5 });
let windTurbinesLayerSource = 'loading';
let evChargersLayerSource = 'loading';
let consumptionAreasLayerSource = 'loading';
const heatLayerSources = Object.fromEntries(
    Pc6MapData.HEAT_LAYER_IDS.map((layerId) => [layerId, 'loading'])
);

const HEAT_LAYER_UI = {
    reported_neighbourhood_heat_consumers: {
        title: 'Neighbourhood heat consumers',
        geometry: 'area',
        fields: [
            ['area_name', 'Area', ''],
            ['reported_connected_share_pct', 'Reported connected share', '%'],
            ['connected_dwellings_estimate', 'Connected dwellings estimate', ''],
            ['heat_demand_estimate_gj_per_year', 'Estimated heat demand', ' GJ/year']
        ]
    },
    inferred_pc6_heat_consumers: {
        title: 'Inferred PC6 heat consumers',
        geometry: 'area',
        fields: [
            ['postcode6', 'PC6', ''],
            ['allocated_connected_dwellings_est', 'Allocated dwellings', ''],
            ['heat_demand_gj_year_est', 'Estimated heat demand', ' GJ/year'],
            ['liander_crosscheck_status', 'Liander cross-check', '']
        ]
    },
    registered_heat_network_developments: {
        title: 'Registered heat-network development',
        geometry: 'area',
        fields: [
            ['development_name', 'Development', ''],
            ['development_phase', 'Phase', ''],
            ['status_date', 'Status date', ''],
            ['planned_heat_source_description', 'Planned source', '']
        ]
    },
    documented_actual_heat_sources: {
        title: 'Documented actual heat source',
        geometry: 'point',
        fields: [
            ['source_name', 'Source', ''],
            ['source_status', 'Status', ''],
            ['technology', 'Technology', '']
        ]
    },
    documented_large_heat_consumers: {
        title: 'Documented large heat consumer',
        geometry: 'point',
        fields: [
            ['consumer_name', 'Consumer', ''],
            ['connection_evidence', 'Connection evidence', ''],
            ['annual_heat_consumption', 'Annual consumption', ' GJ/year']
        ]
    },
    potential_heat_sources: {
        title: 'Potential heat source',
        geometry: 'point',
        fields: [
            ['source_name', 'Source', ''],
            ['source_type', 'Type', ''],
            ['potential_thermal_capacity_mw', 'Potential capacity', ' MWth'],
            ['temperature_c', 'Temperature', ' °C']
        ]
    }
};

// Unified Color Logic
function getColor(d, type) {
    if (type === 'gas') {
        return d > 1500 ? '#800026' : d > 1200 ? '#bd0026' : d > 1000 ? '#e31a1c' :
               d > 800  ? '#fc4e2a' : d > 600  ? '#fd8d3c' : d > 400  ? '#feb24c' : '#fed976';
    } else {
        return d > 4000 ? '#084594' : d > 3500 ? '#2171b5' : d > 3000 ? '#4292c6' :
               d > 2500 ? '#6baed6' : d > 2000 ? '#9ecae1' : d > 1500 ? '#c6dbef' : '#deebf7';
    }
}

function getPvColor(value) {
    return value > 25000 ? '#005a32' : value > 15000 ? '#238b45' :
           value > 7500 ? '#41ab5d' : value > 3000 ? '#78c679' :
           value > 1000 ? '#addd8e' : value > 0 ? '#d9f0a3' : '#f0f0f0';
}

function getConsumptionColor(value) {
    return value > 30000000 ? '#54278f' : value > 15000000 ? '#756bb1' :
           value > 7500000 ? '#9e9ac8' : value > 3000000 ? '#cbc9e2' :
           value > 1000000 ? '#dadaeb' : value > 0 ? '#f2f0f7' : '#f0f0f0';
}

// // Styling Function
// function style(feature) {
//     const val = currentMetric === 'gas' ? feature.properties.p6_gasm3_2023 : feature.properties.p6_kwh_2023;
//     return { 
//         fillColor: getColor(val, currentMetric), 
//         weight: 0.8, 
//         opacity: 0.4, 
//         color: '#ffffff', 
//         fillOpacity: 0.55 
//     };
// }

// Styling Function
// Function to create a dynamic striped pattern for a specific postcode
function createDynamicPattern(pc, colorActual, colorSim) {
    let defs = document.querySelector('svg defs');
    if (!defs) {
        const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        svg.setAttribute("style", "height:0; width:0; position:absolute;");
        defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");
        svg.appendChild(defs);
        document.body.insertBefore(svg, document.body.firstChild);
    }

    const patternId = `pattern-${pc.replace(/\s+/g, '')}`;
    let pattern = document.getElementById(patternId);

    // Create or update the pattern
    if (!pattern) {
        pattern = document.createElementNS("http://www.w3.org/2000/svg", "pattern");
        pattern.setAttribute("id", patternId);
        pattern.setAttribute("patternUnits", "userSpaceOnUse");
        pattern.setAttribute("width", "10");
        pattern.setAttribute("height", "10");
        pattern.setAttribute("patternTransform", "rotate(45)");
        defs.appendChild(pattern);
    }

    pattern.innerHTML = `
        <rect width="10" height="10" fill="${colorActual}"></rect>
        <rect width="5" height="10" fill="${colorSim}"></rect>
    `;

    return patternId;
}

// Updated Styling Function
function style(feature) {
    const pc = feature.properties.postcode6;
    const scenario = postcodeScenarios[pc] || { gas: 1.0, pv: 1.0, modified: false };
    
    // 1. Get Actual Value and Color
    const actualVal = currentMetric === 'gas' ? feature.properties.p6_gasm3_2023 : feature.properties.p6_kwh_2023;
    const colorActual = getColor(actualVal, currentMetric);

    // 2. Get Simulated Value and Color
    const simVal = getCalculatedValue(feature, currentMetric);
    const colorSim = getColor(simVal, currentMetric);

    let styleObj = {
        weight: 0.8,
        opacity: 0.4,
        color: '#ffffff',
        fillOpacity: 0.7
    };

    if (scenario.modified) {
        // Create a unique pattern for this specific change
        const patternId = createDynamicPattern(pc, colorActual, colorSim);
        
        styleObj.fillColor = `url(#${patternId})`;
        styleObj.fillOpacity = 1.0; // Pattern needs full opacity to see colors clearly
        styleObj.weight = 2;
        styleObj.color = colorSim; // Border follows the new simulation color
        styleObj.opacity = 1.0;
    } else {
        styleObj.fillColor = colorActual;
    }

    return styleObj;
}

function pvStyle(feature) {
    return {
        fillColor: getPvColor(Number(feature.properties.pv_capacity_kwp || 0)),
        weight: 0.9,
        opacity: 0.75,
        color: '#ffffff',
        fillOpacity: 0.72
    };
}

function getGridLineColor(voltageLevel) {
    return {
        lv: '#c43d4f',
        mv: '#2378a7',
        hv: '#24292e',
        unknown: '#7f8c8d'
    }[voltageLevel] || '#7f8c8d';
}

function gridLineStyle(feature) {
    return {
        color: getGridLineColor(feature.properties.voltage_level),
        weight: feature.properties.voltage_level === 'lv' ? 3 : 4,
        opacity: 0.9
    };
}

function evChargerStyle(feature) {
    const maximumPower = Number(feature.properties.max_power_kw || 0);
    return {
        radius: maximumPower >= 50 ? 7 : maximumPower >= 22 ? 6 : 5,
        color: '#ffffff',
        weight: 1.5,
        fillColor: '#008b8b',
        fillOpacity: 0.9
    };
}

function consumptionAreaStyle(feature) {
    const isWijk = feature.properties.spatial_unit_type === 'wijk';
    const annualConsumption = feature.properties.annual_electricity_consumption_kwh ??
        feature.properties.annual_electricity_kwh;
    return {
        fillColor: getConsumptionColor(Number(annualConsumption || 0)),
        weight: isWijk ? 2.5 : 0.9,
        opacity: 0.85,
        color: isWijk ? '#3f2b63' : '#ffffff',
        dashArray: isWijk ? '6 4' : null,
        fillOpacity: isWijk ? 0.3 : 0.68
    };
}

function getReachColor(componentId) {
    const colors = ['#16845b', '#9b5d18', '#7a4c9f', '#227ca3', '#a33f50', '#587c2d', '#8b6d1f'];
    const hash = String(componentId || '').split('').reduce(
        (value, character) => ((value * 31) + character.charCodeAt(0)) >>> 0,
        0
    );
    return colors[hash % colors.length];
}

function windTurbineStyle(feature) {
    const capacity = Number(feature.properties.capacity_kw || 0);
    return {
        radius: Math.max(6, Math.min(10, 5 + capacity / 800)),
        color: '#ffffff',
        weight: 2,
        fillColor: '#16856b',
        fillOpacity: 0.95
    };
}

function heatLayerStyle(layerId, feature) {
    return HeatVisualization.layerStyle(layerId, feature);
}

// One colour per EDSN voedingsgebied; a PC6 without one is grey and dashed.
function gridCapacityStyle(feature) {
    const properties = feature.properties || {};
    if (properties.assignment_status !== 'available') {
        return {
            color: '#6b7280', weight: 1.5, opacity: 0.8, fillColor: '#9ca3af',
            fillOpacity: 0.25, dashArray: '4 4'
        };
    }
    const color = voedingsgebiedColor(voedingsgebiedId(properties));
    return { color, weight: 1, opacity: 0.7, fillColor: color, fillOpacity: 0.35 };
}

// Distinct colours, assigned in sorted order once the layer has loaded.
const VOEDINGSGEBIED_PALETTE = [
    '#16845b', '#9b5d18', '#7a4c9f', '#227ca3', '#a33f50',
    '#587c2d', '#c2185b', '#00838f', '#5d4037', '#3949ab'
];
const voedingsgebiedColors = new Map();

function assignVoedingsgebiedColors(collection) {
    const names = new Set();
    collection.features.forEach((feature) => {
        const properties = feature.properties || {};
        if (properties.assignment_status === 'available') names.add(voedingsgebiedId(properties));
    });
    [...names].sort().forEach((name, index) => {
        voedingsgebiedColors.set(name, VOEDINGSGEBIED_PALETTE[index % VOEDINGSGEBIED_PALETTE.length]);
    });
}

function voedingsgebiedColor(name) {
    return voedingsgebiedColors.get(name) || getReachColor(name);
}

function voedingsgebiedId(properties) {
    return properties.withdrawal_service_area_id || properties.injection_service_area_id || '';
}

// Data Loading
function renderLayerStatus(source, fallbackReason = null) {
    const status = document.getElementById('layer-source-status');
    status.dataset.state = source;
    status.textContent = source === 'geoserver_wfs'
        ? 'Live GeoServer WFS'
        : source === 'partial'
            ? 'Some sublayers unavailable'
            : source === 'static_geojson'
                ? 'Static fallback active'
                : source === 'failed'
                    ? 'Layer unavailable'
                    : source === 'empty'
                        ? 'No sublayers selected'
                        : 'Loading layer';
    status.title = fallbackReason || '';
}

function getGridNetworkSource() {
    const sources = Object.values(gridLayerSources);
    if (sources.every((source) => source === 'geoserver_wfs')) return 'geoserver_wfs';
    if (sources.some((source) => source === 'loading')) return 'loading';
    if (sources.some((source) => source === 'geoserver_wfs')) return 'partial';
    return 'failed';
}

function selectedHeatViewIds() {
    return [...document.querySelectorAll('[data-heat-view]:checked')]
        .map((control) => control.dataset.heatView);
}

function selectedHeatLayerIds() {
    return [...new Set(selectedHeatViewIds().map(
        (viewId) => HeatVisualization.sourceLayerId(viewId)
    ))];
}

function getHeatNetworkSource() {
    const selectedSources = selectedHeatLayerIds().map(
        (layerId) => heatLayerSources[layerId]
    );
    if (selectedSources.length === 0) return 'empty';
    if (selectedSources.every((source) => source === 'geoserver_wfs')) return 'geoserver_wfs';
    if (selectedSources.some((source) => source === 'loading')) return 'loading';
    if (selectedSources.some((source) => source === 'geoserver_wfs')) return 'partial';
    return 'failed';
}

function updateLayerStatus(layerName, source, fallbackReason = null) {
    if (layerName === 'pv_capacity') {
        pvLayerSource = source;
    } else if (Object.hasOwn(gridLayerSources, layerName)) {
        gridLayerSources[layerName] = source;
    } else if (layerName === 'public_wind_turbines') {
        windTurbinesLayerSource = source;
    } else if (layerName === 'ev_chargers') {
        evChargersLayerSource = source;
    } else if (layerName === 'consumption_areas') {
        consumptionAreasLayerSource = source;
    } else if (Pc6MapData.HEAT_LAYER_IDS.includes(layerName)) {
        heatLayerSources[layerName] = source;
    } else {
        pc6LayerSource = source;
    }
    const activeLayer = ['gas', 'elec'].includes(currentMetric) ? 'pc6' : currentMetric;
    if (activeLayer === 'grid_network' && Object.hasOwn(gridLayerSources, layerName)) {
        renderLayerStatus(getGridNetworkSource(), fallbackReason);
    } else if (activeLayer === 'heat_network' && Pc6MapData.HEAT_LAYER_IDS.includes(layerName)) {
        renderLayerStatus(getHeatNetworkSource(), fallbackReason);
    } else if (activeLayer === layerName) {
        renderLayerStatus(source, fallbackReason);
    }
}

function refreshLayerStatus() {
    const activeLayer = ['gas', 'elec'].includes(currentMetric) ? 'pc6' : currentMetric;
    const sources = {
        pc6: pc6LayerSource,
        pv_capacity: pvLayerSource,
        grid_network: getGridNetworkSource(),
        ev_chargers: evChargersLayerSource,
        consumption_areas: consumptionAreasLayerSource,
        public_wind_turbines: windTurbinesLayerSource,
        heat_network: getHeatNetworkSource(),
        ...heatLayerSources
    };
    renderLayerStatus(sources[activeLayer]);
}

function updateLayerQualitySummary() {
    const label = document.getElementById('layer-quality-label');
    const meter = document.getElementById('layer-quality-meter');
    const isPvCapacity = currentMetric === 'pv_capacity';
    const isGrid = currentMetric === 'grid_network';
    const isEv = currentMetric === 'ev_chargers';
    const isConsumption = currentMetric === 'consumption_areas';
    const isWind = currentMetric === 'public_wind_turbines';
    const isHeat = currentMetric === 'heat_network';
    label.textContent = (isGrid || isWind || isHeat)
        ? 'Datacompleetheid per component'
        : isEv ? 'Datacompleetheid 0-2/3'
            : isConsumption ? 'Datacompleetheid 1-2/3'
            : isPvCapacity ? 'Datacompleetheid 1-2/3' : 'Datacompleetheid 2/3';
    meter.title = (isPvCapacity || isGrid || isWind || isHeat || isEv || isConsumption)
        ? 'Feature-level confidence varies across this layer'
        : 'Layer-level confidence';
}

function gridControlChecked(id) {
    return Boolean(document.getElementById(id)?.checked);
}

function allGridLayers() {
    return [gridCapacityLayer, gridMvLinesLayer].filter(Boolean);
}

function selectedGridLayers() {
    const layers = [];
    if (gridControlChecked('grid-capacity-areas') && gridCapacityLayer) layers.push(gridCapacityLayer);
    if (gridControlChecked('grid-mv-lines') && gridMvLinesLayer) layers.push(gridMvLinesLayer);
    return layers;
}

function applyGridVisibility(fit = false) {
    allGridLayers().forEach((layer) => {
        if (map.hasLayer(layer)) map.removeLayer(layer);
    });
    if (currentMetric !== 'grid_network') return;

    const visibleLayers = selectedGridLayers();
    visibleLayers.forEach((layer) => layer.addTo(map));
    if (gridMvLinesLayer && map.hasLayer(gridMvLinesLayer)) gridMvLinesLayer.bringToFront();
    if (fit && visibleLayers.length > 0) {
        const bounds = L.featureGroup(visibleLayers).getBounds();
        if (bounds.isValid()) {
            map.fitBounds(bounds, { padding: [24, 24] });
            gridHasFit = true;
        }
    }
}

function updateGridVisibilityPanel() {
    document.getElementById('grid-visibility').hidden = currentMetric !== 'grid_network';
}

function allHeatLayers() {
    return Object.values(heatMapLayers).filter(Boolean);
}

function selectedHeatLayers() {
    return selectedHeatViewIds()
        .map((viewId) => heatMapLayers[viewId])
        .filter(Boolean);
}

function applyHeatVisibility(fit = false) {
    allHeatLayers().forEach((layer) => {
        if (map.hasLayer(layer)) map.removeLayer(layer);
    });
    if (currentMetric !== 'heat_network') return;

    const visibleLayers = selectedHeatLayers();
    visibleLayers.forEach((layer) => layer.addTo(map));
    HeatVisualization.HEAT_VIEW_IDS.forEach((viewId) => {
        const layer = heatMapLayers[viewId];
        if (layer && map.hasLayer(layer) && layer.bringToFront) layer.bringToFront();
    });
    if (fit && visibleLayers.length > 0) {
        const bounds = L.featureGroup(visibleLayers).getBounds();
        if (bounds.isValid()) {
            map.fitBounds(bounds, { padding: [24, 24] });
            heatHasFit = true;
        }
    }
}

function updateHeatVisibilityPanel() {
    const isHeat = currentMetric === 'heat_network';
    document.getElementById('heat-visibility').hidden = !isHeat;
    document.getElementById('heat-evidence-summary').hidden = !isHeat;
}

function updateHeatEvidenceSummary() {
    const neighbourhoods = heatFeatureCollections.reported_neighbourhood_heat_consumers;
    const pc6 = heatFeatureCollections.inferred_pc6_heat_consumers;
    if (neighbourhoods) {
        const connectedDwellings = neighbourhoods.features.reduce(
            (total, feature) => total + (Number(feature.properties?.connected_dwellings_estimate) || 0),
            0
        );
        const demandGj = neighbourhoods.features.reduce(
            (total, feature) => total + (Number(feature.properties?.heat_demand_estimate_gj_per_year) || 0),
            0
        );
        const neighbourhoodCount = neighbourhoods.features.length;
        document.getElementById('heat-summary-consumers').textContent =
            `${neighbourhoodCount.toLocaleString('nl-NL')} ` +
            `neighbourhood${neighbourhoodCount === 1 ? '' : 's'}; ` +
            `${Math.round(connectedDwellings).toLocaleString('nl-NL')} connected dwellings; ` +
            `${(demandGj / 1000).toLocaleString('nl-NL', { maximumFractionDigits: 1 })} TJ/year`;
    }
    if (pc6) {
        const signalFeatures = pc6.features.filter((feature) => [
            'strong_low_gas_normal_electricity',
            'moderate_low_gas_normal_electricity'
        ].includes(feature.properties?.inference_class));
        const checks = { supports: 0, conflicts: 0, inconclusive: 0 };
        signalFeatures.forEach((feature) => {
            const status = String(feature.properties?.liander_crosscheck_status || '');
            if (status.startsWith('supports_')) checks.supports += 1;
            else if (status.startsWith('conflicts_')) checks.conflicts += 1;
            else checks.inconclusive += 1;
        });
        const outsideCount = signalFeatures.filter(
            (feature) => feature.properties?.corroboration !== 'reported_heat_neighbourhood'
        ).length;
        document.getElementById('heat-summary-pc6').textContent =
            `${signalFeatures.length.toLocaleString('nl-NL')} low-gas PC6 signals; ` +
            `${outsideCount.toLocaleString('nl-NL')} outside reported neighbourhoods`;
        document.getElementById('heat-summary-crosscheck').textContent =
            `Liander: ${checks.supports} support / ${checks.conflicts} conflict / ` +
            `${checks.inconclusive} inconclusive`;
    }
}

function setActiveMapLayer(fitActive = false) {
    const independentLayers = {
        pc6: pc6Layer,
        pv_capacity: pvLayer,
        ev_chargers: evChargersLayer,
        consumption_areas: consumptionAreasLayer,
        public_wind_turbines: windTurbinesLayer
    };
    const activeLayerName = ['gas', 'elec'].includes(currentMetric) ? 'pc6' : currentMetric;
    Object.entries(independentLayers).forEach(([layerName, layer]) => {
        if (layer && layerName !== activeLayerName && map.hasLayer(layer)) {
            map.removeLayer(layer);
        }
    });
    applyGridVisibility(fitActive || (currentMetric === 'grid_network' && !gridHasFit));
    applyHeatVisibility(fitActive || (currentMetric === 'heat_network' && !heatHasFit));

    const activeLayer = independentLayers[activeLayerName];
    if (activeLayer && !map.hasLayer(activeLayer)) {
        activeLayer.addTo(map);
        if (activeLayerName !== 'pc6' && activeLayer.getLayers().length > 0) {
            map.fitBounds(activeLayer.getBounds());
        }
    }
    if (activeLayerName === 'pc6' && pc6Layer) pc6Layer.setStyle(style);
    updateGridVisibilityPanel();
    updateHeatVisibilityPanel();
    refreshLayerStatus();
    updateLayerQualitySummary();
    updateLegend();
}

function createHeatMapLayer(layerId, featureCollection) {
    const config = HEAT_LAYER_UI[layerId];
    return L.geoJSON(featureCollection, {
        style: (feature) => heatLayerStyle(layerId, feature),
        pointToLayer: (feature, latlng) => L.circleMarker(
            latlng,
            heatLayerStyle(layerId, feature)
        ),
        onEachFeature: (feature, layer) => {
            layer.on({
                mouseover: (event) => event.target.setStyle({ weight: 4 }),
                mouseout: (event) => event.target.setStyle(
                    heatLayerStyle(layerId, feature)
                ),
                click: (event) => {
                    updateHeatSidePanel(layerId, feature.properties);
                    if (config.geometry === 'point') {
                        map.setView(event.target.getLatLng(), Math.max(map.getZoom(), 15));
                    } else {
                        map.fitBounds(event.target.getBounds(), {
                            padding: [40, 40],
                            maxZoom: 16
                        });
                    }
                }
            });
        }
    });
}

async function loadMap() {
    try {
        const result = await Pc6MapData.loadPc6FeatureCollection(fetch);
        const data = result.data;
        updateLayerStatus('pc6', result.source, result.fallbackReason);
        if (result.fallbackReason) {
            console.warn('GeoServer WFS unavailable; using static fallback:', result.fallbackReason);
        }

        pc6Layer = L.geoJSON(data, {
            style: style,
            onEachFeature: (feature, layer) => {
                layer.on({
                    mouseover: (e) => {
                        e.target.setStyle({ weight: 2, color: '#2f3640', fillOpacity: 0.7 });
                    },
                    mouseout: (e) => {
                        pc6Layer.resetStyle(e.target);
                    },
                    click: (e) => {
                        updateSidePanel(feature.properties);
                        map.fitBounds(e.target.getBounds(), { padding: [40, 40], maxZoom: 17 });
                    }
                });
            }
        });
        pc6Layer.addTo(map);

        if (data.features.length > 0) {
            map.fitBounds(pc6Layer.getBounds());
        }
    } catch (e) {
        console.error('PC6 data load failed:', e);
        updateLayerStatus('pc6', 'failed', e.message);
    }

    try {
        const result = await Pc6MapData.loadPvFeatureCollection(fetch);
        pvLayer = L.geoJSON(result.data, {
            style: pvStyle,
            onEachFeature: (feature, layer) => {
                layer.on({
                    mouseover: (e) => {
                        e.target.setStyle({ weight: 2, color: '#2f3640', fillOpacity: 0.82 });
                    },
                    mouseout: (e) => {
                        pvLayer.resetStyle(e.target);
                    },
                    click: (e) => {
                        updatePvSidePanel(feature.properties);
                        map.fitBounds(e.target.getBounds(), { padding: [40, 40], maxZoom: 16 });
                    }
                });
            }
        });
        updateLayerStatus('pv_capacity', result.source);
    } catch (e) {
        console.error('PV capacity data load failed:', e);
        updateLayerStatus('pv_capacity', 'failed', e.message);
        const pvControl = document.getElementById('r-pv-capacity');
        pvControl.disabled = true;
        pvControl.parentElement.title = 'PV capacity layer is unavailable';
    }

    try {
        const result = await Pc6MapData.loadEvChargersFeatureCollection(fetch);
        evChargersLayer = L.geoJSON(result.data, {
            pointToLayer: (feature, latlng) => L.circleMarker(
                latlng,
                evChargerStyle(feature)
            ),
            onEachFeature: (feature, layer) => {
                layer.on({
                    mouseover: (event) => event.target.setStyle({ weight: 3 }),
                    mouseout: (event) => event.target.setStyle(evChargerStyle(feature)),
                    click: (event) => {
                        updateEvSidePanel(feature.properties);
                        map.setView(event.target.getLatLng(), Math.max(map.getZoom(), 16));
                    }
                });
            }
        });
        updateLayerStatus('ev_chargers', result.source);
    } catch (error) {
        console.error('EV charger data load failed:', error);
        updateLayerStatus('ev_chargers', 'failed', error.message);
        const control = document.getElementById('r-ev-chargers');
        control.disabled = true;
        control.parentElement.title = 'EV charger layer is unavailable';
    }

    try {
        const result = await Pc6MapData.loadConsumptionAreasFeatureCollection(fetch);
        consumptionAreasLayer = L.geoJSON(result.data, {
            style: consumptionAreaStyle,
            onEachFeature: (feature, layer) => {
                layer.on({
                    mouseover: (event) => event.target.setStyle({ weight: 2.5, color: '#2f3640' }),
                    mouseout: (event) => consumptionAreasLayer.resetStyle(event.target),
                    click: (event) => {
                        updateConsumptionSidePanel(feature.properties);
                        map.fitBounds(event.target.getBounds(), { padding: [40, 40], maxZoom: 15 });
                    }
                });
            }
        });
        updateLayerStatus('consumption_areas', result.source);
    } catch (error) {
        console.error('Consumption area data load failed:', error);
        updateLayerStatus('consumption_areas', 'failed', error.message);
        const control = document.getElementById('r-consumption-areas');
        control.disabled = true;
        control.parentElement.title = 'Consumption map layer is unavailable';
    }

    try {
        const result = await Pc6MapData.loadGridCapacityFeatureCollection(fetch);
        assignVoedingsgebiedColors(result.data);
        gridCapacityLayer = L.geoJSON(result.data, {
            renderer: gridCanvasRenderer,
            style: gridCapacityStyle,
            onEachFeature: (feature, layer) => {
                layer.on({
                    mouseover: (event) => event.target.setStyle({ weight: 3, fillOpacity: 0.55 }),
                    mouseout: (event) => event.target.setStyle(gridCapacityStyle(feature)),
                    click: (event) => {
                        updateGridCapacitySidePanel(feature.properties);
                        map.fitBounds(event.target.getBounds(), { padding: [40, 40], maxZoom: 16 });
                    }
                });
            }
        });
        updateLayerStatus('grid_capacity_limits', result.source);
    } catch (error) {
        console.error('Grid capaciteitskaart load failed:', error);
        updateLayerStatus('grid_capacity_limits', 'failed', error.message);
        const control = document.getElementById('grid-capacity-areas');
        control.disabled = true;
        control.parentElement.title = 'Voedingsgebied layer is unavailable';
    }

    try {
        const result = await Pc6MapData.loadGridMvLinesFeatureCollection(fetch);
        gridMvLinesLayer = L.geoJSON(result.data, {
            renderer: gridCanvasRenderer,
            style: gridLineStyle,
            onEachFeature: (feature, layer) => {
                layer.on({
                    mouseover: (event) => event.target.setStyle({ weight: 6 }),
                    mouseout: (event) => event.target.setStyle(gridLineStyle(feature)),
                    click: (event) => {
                        updateGridLineSidePanel(feature.properties);
                        map.fitBounds(event.target.getBounds(), { padding: [40, 40], maxZoom: 18 });
                    }
                });
            }
        });
        updateLayerStatus('grid_mv_lines', result.source);
    } catch (error) {
        console.error('Grid MV lines load failed:', error);
        updateLayerStatus('grid_mv_lines', 'failed', error.message);
        const control = document.getElementById('grid-mv-lines');
        control.disabled = true;
        control.parentElement.title = 'MV lines layer is unavailable';
    }

    try {
        const result = await Pc6MapData.loadWindTurbinesFeatureCollection(fetch);
        windTurbinesLayer = L.geoJSON(result.data, {
            pointToLayer: (feature, latlng) => L.circleMarker(latlng, windTurbineStyle(feature)),
            onEachFeature: (feature, layer) => {
                layer.on({
                    mouseover: (event) => event.target.setStyle({ weight: 4 }),
                    mouseout: (event) => event.target.setStyle(windTurbineStyle(feature)),
                    click: (event) => {
                        updateWindTurbineSidePanel(feature.properties);
                        map.setView(event.target.getLatLng(), Math.max(map.getZoom(), 15));
                    }
                });
            }
        });
        updateLayerStatus('public_wind_turbines', result.source);
    } catch (error) {
        console.error('Wind turbine data load failed:', error);
        updateLayerStatus('public_wind_turbines', 'failed', error.message);
        const control = document.getElementById('r-wind-turbines');
        control.disabled = true;
        control.parentElement.title = 'Wind turbine layer is unavailable';
    }

    await Promise.all(Pc6MapData.HEAT_LAYER_IDS.map(async (layerId) => {
        try {
            const result = await Pc6MapData.loadHeatFeatureCollection(fetch, layerId);
            heatFeatureCollections[layerId] = result.data;
            HeatVisualization.HEAT_VIEW_IDS
                .filter((viewId) => HeatVisualization.sourceLayerId(viewId) === layerId)
                .forEach((viewId) => {
                    const viewCollection = HeatVisualization.viewCollection(
                        viewId,
                        result.data
                    );
                    heatMapLayers[viewId] = createHeatMapLayer(layerId, viewCollection);
                });
            updateHeatEvidenceSummary();
            updateLayerStatus(layerId, result.source);
        } catch (error) {
            console.error(`${layerId} data load failed:`, error);
            updateLayerStatus(layerId, 'failed', error.message);
            document.querySelectorAll(`[data-heat-source="${layerId}"]`)
                .forEach((control) => {
                    control.disabled = true;
                    control.checked = false;
                    control.parentElement.title = 'Layer unavailable';
                });
        }
    }));

    setActiveMapLayer();
}

// Search Logic
function searchPostcode() {
    const input = document.getElementById('search-input').value.replace(/\s+/g, '').toUpperCase();
    let found = false;

    if (!pc6Layer) return;

    pc6Layer.eachLayer((layer) => {
        const pc = (layer.feature.properties.postcode6 || "").replace(/\s+/g, '').toUpperCase();
        if (pc === input) {
            found = true;
            updateSidePanel(layer.feature.properties);
            map.fitBounds(layer.getBounds(), { padding: [40, 40] });
            layer.setStyle({weight: 3, color: '#1e272e', fillOpacity: 0.8});
        }
    });

    if (!found) alert("Record not found.");
}

// Update Legend
function updateLegend() {
    const existing = document.querySelector('.legend');
    if (existing) existing.remove();

    const legend = L.control({position: 'bottomright'});

    legend.onAdd = function () {
        const div = L.DomUtil.create('div', 'info legend');
        if (currentMetric === 'grid_network') {
            div.innerHTML = '<div class="legend-title">ELECTRICITY GRID</div>';
            const entries = [['grid-mv-lines', '#2378a7', 'MV lines']];
            if (gridControlChecked('grid-capacity-areas')) {
                gridVoedingsgebieden().forEach((name) => {
                    div.innerHTML += `<i style="background:${voedingsgebiedColor(name)};opacity:0.6"></i> ${escapeHtml(name)}<br>`;
                });
                div.innerHTML += '<i style="background:#9ca3af;opacity:0.5"></i> Geen voedingsgebied gepubliceerd<br>';
            }
            entries.filter(([id]) => gridControlChecked(id)).forEach(([, color, label]) => {
                div.innerHTML += `<i style="background:${color}"></i> ${label}<br>`;
            });
            if (selectedGridLayers().length === 0) {
                div.innerHTML += 'No grid components selected';
            }
            return div;
        }
        if (currentMetric === 'public_wind_turbines') {
            div.innerHTML = '<div class="legend-title">WIND TURBINES</div>';
            div.innerHTML += '<i style="background:#16856b"></i> Published position and capacity<br>';
            return div;
        }
        if (currentMetric === 'ev_chargers') {
            div.innerHTML = '<div class="legend-title">PUBLIC EV CHARGERS</div>';
            div.innerHTML += '<i class="point-legend" style="background:#008b8b"></i> Charging location<br>';
            return div;
        }
        if (currentMetric === 'heat_network') {
            const selected = new Set(selectedHeatViewIds());
            div.innerHTML = '<div class="legend-title">HEAT EVIDENCE</div>';
            if (selected.has('reported_neighbourhood_heat_consumers')) {
                div.innerHTML += '<i class="heat-gradient"></i> Neighbourhood connected share (0-100%)<br>';
            }
            if (selected.has('allocated_pc6_heat_consumers')) {
                div.innerHTML += '<i style="background:#084594"></i> Strong allocated PC6 evidence<br>';
                div.innerHTML += '<i style="background:#4292c6"></i> Moderate allocated PC6 evidence<br>';
                div.innerHTML += '<i style="background:#c6dbef"></i> Fallback PC6 allocation<br>';
                div.innerHTML += '<i class="heat-outline-support"></i> Liander supports<br>';
                div.innerHTML += '<i class="heat-outline-conflict"></i> Liander conflicts<br>';
                div.innerHTML += '<i class="heat-outline-inconclusive"></i> Liander inconclusive<br>';
            }
            if (selected.has('unallocated_pc6_heat_signals')) {
                div.innerHTML += '<i style="background:#fdbb30"></i> Signal only, not allocated<br>';
            }
            if (selected.has('excluded_electric_heating_pc6')) {
                div.innerHTML += '<i style="background:#9e9ac8"></i> Possible electric heating excluded<br>';
            }
            if (selected.has('registered_heat_network_developments')) {
                div.innerHTML += '<i class="heat-development"></i> Registered network development<br>';
            }
            if (selected.has('documented_actual_heat_sources')) {
                div.innerHTML += '<i class="point-legend" style="background:#cb181d"></i> Actual heat source<br>';
            }
            if (selected.has('documented_large_heat_consumers')) {
                div.innerHTML += '<i class="point-legend" style="background:#2171b5"></i> Large heat consumer<br>';
            }
            if (selected.has('potential_heat_sources')) {
                div.innerHTML += '<i class="point-legend" style="background:#238b45"></i> Potential heat source<br>';
            }
            if (selected.size === 0) div.innerHTML += 'No heat evidence selected';
            return div;
        }
        if (currentMetric === 'consumption_areas') {
            const grades = [0, 1000000, 3000000, 7500000, 15000000, 30000000];
            div.innerHTML = '<div class="legend-title">ANNUAL ELECTRICITY (kWh)</div>';
            grades.forEach((grade, index) => {
                const upper = grades[index + 1];
                const label = `${(grade / 1000000).toLocaleString('nl-NL')}${upper ? `-${upper / 1000000}` : '+'} M`;
                div.innerHTML += `<i style="background:${getConsumptionColor(grade + 1)}"></i> ${label}<br>`;
            });
            return div;
        }
        const isPvCapacity = currentMetric === 'pv_capacity';
        const grades = isPvCapacity ? [0, 1000, 3000, 7500, 15000, 25000] :
            currentMetric === 'gas' ? [0, 400, 600, 800, 1000, 1200, 1500] :
            [0, 1500, 2000, 2500, 3000, 3500, 4000];
        const title = isPvCapacity ? 'PV CAPACITY (kWp)' :
            currentMetric === 'gas' ? 'GAS (m³)' : 'ELEC (kWh)';
        
        div.innerHTML = `<div style="margin-bottom:8px; font-weight:700; font-size:9px;">${title}</div>`;
        
        grades.forEach((g, i) => {
            const color = isPvCapacity ? getPvColor(g + 1) : getColor(g + 1, currentMetric);
            div.innerHTML += `<i style="background:${color}"></i> ${g}${grades[i+1] ? '&ndash;'+grades[i+1] : '+'}<br>`;
        });
        return div;
    };
    legend.addTo(map);
}

// Global object to store local overrides
// Format: { "1811AA": { gas: 0.5, pv: 2.0 }, ... }
let postcodeScenarios = {};
let selectedScenarioPostcode = null;
let selectedScenarioProperties = null;
let scenarioDraft = { gas: 1.0, pv: 1.0, modified: false };
let scenarioRunning = false;
let selectedTransformerProfileSource = null;
let transformerProfileRunning = false;
let transformerProfileResult = null;
let activeTransformerProfileStage = 'lv_mv';
let preferredTransformerProfileId = null;
let transformerProfileHighlightLayer = null;

function getActiveScenario() {
    return selectedScenarioPostcode
        ? postcodeScenarios[selectedScenarioPostcode]
        : scenarioDraft;
}

function updateScenarioControls() {
    const scenario = getActiveScenario();
    const target = document.getElementById('scenario-target');
    const targetValue = document.getElementById('scenario-target-value');
    const runButton = document.getElementById('run-sim-btn');

    document.getElementById('input-gas').value = scenario.gas * 100;
    document.getElementById('input-pv').value = scenario.pv * 100;
    document.getElementById('pct-gas').innerText = `${Math.round(scenario.gas * 100)}%`;
    document.getElementById('pct-pv').innerText = `${Math.round(scenario.pv * 100)}%`;

    target.dataset.state = selectedScenarioPostcode ? 'selected' : 'empty';
    targetValue.innerText = selectedScenarioPostcode || 'No PC6 selected';
    runButton.disabled = !selectedScenarioPostcode || scenarioRunning;
    runButton.title = selectedScenarioPostcode
        ? `Run scenario for ${selectedScenarioPostcode}`
        : 'Select a PC6 feature or search for a postcode before running';
}

function selectScenarioTarget(prop) {
    const pc = prop.postcode6;
    if (!postcodeScenarios[pc]) {
        postcodeScenarios[pc] = { ...scenarioDraft };
    }
    selectedScenarioPostcode = pc;
    selectedScenarioProperties = prop;
    selectTransformerProfileSource({ type: 'pc6', id: pc, label: pc });
    updateScenarioControls();
}

function selectScenarioTargetByPc6(pc6Id) {
    if (!pc6Layer || !pc6Id) return;
    const normalized = String(pc6Id).replace(/\s+/g, '').toUpperCase();
    pc6Layer.eachLayer((layer) => {
        const properties = layer.feature?.properties || {};
        const candidate = String(properties.postcode6 || '')
            .replace(/\s+/g, '')
            .toUpperCase();
        if (candidate === normalized) selectScenarioTarget(properties);
    });
}

function initializeScenarioControls() {
    document.getElementById('input-gas').addEventListener('input', (event) => {
        const scenario = getActiveScenario();
        scenario.gas = event.target.value / 100;
        scenario.modified = true;
        document.getElementById('pct-gas').innerText = `${event.target.value}%`;
        if (selectedScenarioProperties) refreshVisuals(selectedScenarioProperties);
    });

    document.getElementById('input-pv').addEventListener('input', (event) => {
        const scenario = getActiveScenario();
        scenario.pv = event.target.value / 100;
        scenario.modified = true;
        document.getElementById('pct-pv').innerText = `${event.target.value}%`;
        if (selectedScenarioProperties) refreshVisuals(selectedScenarioProperties);
    });

    document.getElementById('run-sim-btn').addEventListener('click', () => {
        if (!selectedScenarioPostcode) return;
        runPythonSimulation(
            selectedScenarioPostcode,
            postcodeScenarios[selectedScenarioPostcode]
        );
    });

    updateScenarioControls();
}

function resetTransformerProfileOutput({ keepPreferredTarget = false } = {}) {
    transformerProfileResult = null;
    activeTransformerProfileStage = 'lv_mv';
    if (!keepPreferredTarget) preferredTransformerProfileId = null;
    const output = document.getElementById('transformer-profile-output');
    output.hidden = true;
    if (transformerProfileChart) {
        transformerProfileChart.destroy();
        transformerProfileChart = null;
    }
    clearTransformerProfileHighlight();
}

function clearTransformerProfileHighlight() {
    if (transformerProfileHighlightLayer && map.hasLayer(transformerProfileHighlightLayer)) {
        map.removeLayer(transformerProfileHighlightLayer);
    }
    transformerProfileHighlightLayer = null;
}

// The map no longer draws the transformers as a layer. Their positions are
// fetched once, when a transformer profile is first shown, to mark it on the map.
let gridTransformerPositions = null;
let transformerHighlightRequest = 0;

function loadTransformerPositions() {
    if (!gridTransformerPositions) {
        gridTransformerPositions = Pc6MapData.loadGridTransformersFeatureCollection(fetch)
            .then((result) => new Map(result.data.features
                .filter((feature) => feature.geometry?.type === 'Point')
                .map((feature) => [
                    String(feature.properties?.component_id || ''),
                    L.latLng(feature.geometry.coordinates[1], feature.geometry.coordinates[0])
                ])))
            .catch((error) => {
                console.warn('Transformer positions are unavailable:', error);
                gridTransformerPositions = null;
                return new Map();
            });
    }
    return gridTransformerPositions;
}

async function highlightTransformerProfileTarget(target) {
    clearTransformerProfileHighlight();
    const request = ++transformerHighlightRequest;
    const position = (await loadTransformerPositions()).get(target.id);
    if (!position || request !== transformerHighlightRequest) return;
    const transformerType = target.transformerLevel === 'mv_hv_transformer' ? 'mv_hv' : 'lv_mv';
    transformerProfileHighlightLayer = L.circleMarker(position, {
        radius: transformerType === 'mv_hv' ? 15 : 13,
        color: '#151515',
        weight: 4,
        fillColor: '#f5c542',
        fillOpacity: 0.92,
        interactive: false
    }).addTo(map);
    transformerProfileHighlightLayer.bringToFront();
}

function setTransformerProfileStatus(message = '', state = '') {
    const status = document.getElementById('transformer-profile-status');
    status.innerText = message;
    if (state) status.dataset.state = state;
    else delete status.dataset.state;
}

function updateTransformerProfileControls() {
    const sourceContainer = document.getElementById('transformer-profile-source');
    const sourceValue = document.getElementById('transformer-profile-source-value');
    const loadButton = document.getElementById('load-transformer-profiles-btn');
    const source = selectedTransformerProfileSource;

    sourceContainer.dataset.state = source ? 'selected' : 'empty';
    sourceValue.innerText = source?.id || 'No supported area selected';
    sourceValue.title = source?.label || '';
    loadButton.disabled = !source || transformerProfileRunning;
    loadButton.innerText = transformerProfileRunning
        ? 'CALCULATING...'
        : 'CALCULATE PROFILES';

}

function selectTransformerProfileSource(source) {
    let normalized;
    try {
        normalized = TransformerProfiles.normalizeSource(source);
    } catch (error) {
        console.warn('Unsupported transformer profile source:', error);
        return;
    }
    const previousKey = selectedTransformerProfileSource
        ? `${selectedTransformerProfileSource.type}:${selectedTransformerProfileSource.id}`
        : '';
    const nextKey = `${normalized.type}:${normalized.id}`;
    selectedTransformerProfileSource = normalized;
    if (previousKey !== nextKey) {
        resetTransformerProfileOutput();
        setTransformerProfileStatus();
    }
    updateTransformerProfileControls();
}

function transformerProfileError(payload, status) {
    const detail = payload?.detail;
    if (typeof detail === 'string' && detail) return detail;
    if (detail && typeof detail === 'object') {
        if (typeof detail.message === 'string') return detail.message;
        if (typeof detail.code === 'string') return detail.code.replaceAll('_', ' ');
    }
    return `Transformer profile request failed (${status}).`;
}

function renderTransformerProfileChart(target) {
    const data = TransformerProfiles.chartData(target);
    const canvas = document.getElementById('transformer-profile-canvas');
    if (transformerProfileChart) transformerProfileChart.destroy();
    transformerProfileChart = new Chart(canvas.getContext('2d'), {
        type: 'line',
        data: {
            datasets: [
                {
                    label: 'Demand',
                    data: data.demand,
                    borderColor: '#2980b9',
                    borderWidth: 2,
                    pointRadius: 0
                },
                {
                    label: 'Production',
                    data: data.production,
                    borderColor: '#d97706',
                    borderWidth: 2,
                    pointRadius: 0
                },
                {
                    label: 'Net',
                    data: data.net,
                    borderColor: '#1e272e',
                    borderWidth: 2,
                    pointRadius: 0
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            normalized: true,
            parsing: false,
            interaction: { mode: 'index', intersect: false },
            scales: {
                x: {
                    type: 'time',
                    time: { unit: 'hour', displayFormats: { hour: 'HH:mm' } },
                    ticks: { font: { size: 8 }, maxRotation: 0 }
                },
                y: {
                    title: { display: true, text: 'kW', font: { size: 9 } },
                    ticks: { font: { size: 8 } }
                }
            },
            plugins: {
                decimation: {
                    enabled: true,
                    algorithm: 'lttb',
                    samples: 1000
                },
                legend: {
                    position: 'top',
                    labels: { boxWidth: 10, font: { size: 9 } }
                }
            }
        }
    });
}

function renderTransformerProfileTarget(target) {
    const summary = document.getElementById('transformer-profile-summary');
    const mode = transformerProfileResult.aggregationMode
        .replace('two_stage_', '')
        .replaceAll('_', ' ');
    const contributorCounts = target.raw.contributor_counts || {};
    const contributorTotal = (
        Number(contributorCounts.consumption_pc6 || 0)
        + Number(contributorCounts.pv_cbs_buurt || 0)
    );
    summary.innerHTML = `
        <span>${target.points.length} × ${escapeHtml(transformerProfileResult.resolution)}</span>
        <span>${contributorTotal.toLocaleString('nl-NL')} contributors</span>
        <strong>${escapeHtml(mode)}<br>Datacompleetheid ${transformerProfileResult.datacompleetheid}/3</strong>
    `;
    renderTransformerProfileChart(target);
    highlightTransformerProfileTarget(target);
}

function renderTransformerProfileStage(preferredId = null) {
    if (!transformerProfileResult) return;
    document.querySelectorAll('[data-profile-stage]').forEach((button) => {
        button.setAttribute(
            'aria-pressed',
            String(button.dataset.profileStage === activeTransformerProfileStage)
        );
    });

    const targets = transformerProfileResult.stages[activeTransformerProfileStage].targets;
    const select = document.getElementById('transformer-profile-select');
    select.innerHTML = targets.map((target) => (
        `<option value="${escapeHtml(target.id)}">${escapeHtml(target.label)}</option>`
    )).join('');
    const matchingId = targets.some((target) => target.id === preferredId)
        ? preferredId
        : targets[0].id;
    select.value = matchingId;
    renderTransformerProfileTarget(
        targets.find((target) => target.id === matchingId) || targets[0]
    );
}

async function loadTransformerProfiles() {
    if (!selectedTransformerProfileSource || transformerProfileRunning) return;
    let request;
    try {
        request = TransformerProfiles.buildRequest(selectedTransformerProfileSource);
    } catch (error) {
        setTransformerProfileStatus(error.message, 'error');
        return;
    }

    transformerProfileRunning = true;
    resetTransformerProfileOutput({ keepPreferredTarget: true });
    updateTransformerProfileControls();
    setTransformerProfileStatus('Calculating transformer profiles...');
    try {
        const response = await fetch(request.url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(transformerProfileError(payload, response.status));
        if (
            selectedTransformerProfileSource?.type !== request.source.type ||
            selectedTransformerProfileSource?.id !== request.source.id
        ) {
            throw new Error('The selected map feature changed while profiles were calculated.');
        }
        transformerProfileResult = TransformerProfiles.normalizeResponse(
            payload,
            request.source.id
        );
        activeTransformerProfileStage = 'lv_mv';
        document.getElementById('transformer-profile-output').hidden = false;
        renderTransformerProfileStage(preferredTransformerProfileId);
        setTransformerProfileStatus(
            `${transformerProfileResult.sourceFeatureId} profiles calculated.`
        );
    } catch (error) {
        console.error('Transformer profile calculation failed:', error);
        setTransformerProfileStatus(error.message, 'error');
    } finally {
        transformerProfileRunning = false;
        updateTransformerProfileControls();
    }
}

function initializeTransformerProfileControls() {
    document.getElementById('load-transformer-profiles-btn')
        .addEventListener('click', loadTransformerProfiles);
    document.querySelectorAll('[data-profile-stage]').forEach((button) => {
        button.addEventListener('click', () => {
            if (!transformerProfileResult) return;
            activeTransformerProfileStage = button.dataset.profileStage;
            renderTransformerProfileStage();
        });
    });
    document.getElementById('transformer-profile-select').addEventListener('change', (event) => {
        if (!transformerProfileResult) return;
        const targets = transformerProfileResult.stages[activeTransformerProfileStage].targets;
        const target = targets.find((candidate) => candidate.id === event.target.value);
        if (target) renderTransformerProfileTarget(target);
    });
    updateTransformerProfileControls();
}


function getCalculatedValue(feature, metric) {
    const pc = feature.properties.postcode6;
    const scenario = postcodeScenarios[pc] || { gas: 1.0, pv: 1.0 };
    
    const origGas = feature.properties.p6_gasm3_2023 || 0;
    const origElec = feature.properties.p6_kwh_2023 || 0;
    const origPV = feature.properties.p6_kwh_productie_2023 || 0;

    if (metric === 'gas') return origGas * scenario.gas;
    
    if (metric === 'pv') return origPV * scenario.pv;

    if (metric === 'elec') {
        const gasSaved = origGas * (1 - scenario.gas);
        return origElec + (gasSaved * 3); // Heat pump transition factor
        // TODO replace func 
    }
}

function updateSidePanel(prop) {
    const pc = prop.postcode6;
    
    selectScenarioTarget(prop);
    const s = postcodeScenarios[pc];

    const actualGas = prop.p6_gasm3_2023 || 0;
    const actualElec = prop.p6_kwh_2023 || 0;
    const actualPV = prop.p6_kwh_productie_2023 || 0;

    const scenarioGas = getCalculatedValue({properties: prop}, 'gas');
    const scenarioElec = getCalculatedValue({properties: prop}, 'elec');
    const scenarioPV = getCalculatedValue({properties: prop}, 'pv');
    
    const formatNum = (val) => Math.round(val).toLocaleString('nl-NL');
    const simActiveClass = s.modified ? "active" : "";
    const completeness = Number(prop.datacompleetheid ?? 2);
    const completenessLabel = prop.datacompleetheid_label || 'redelijke betrouwbaarheid';
    const sourceLabel = pc6LayerSource === 'geoserver_wfs'
        ? 'GeoServer WFS' : 'Static GeoJSON fallback';

    document.getElementById('panel-content').innerHTML = `
        <div class="pc6-header">${pc}</div>
        
        <div class="data-grid">
            <div class="data-column">
                <div class="column-header">Actual (2023)</div>
                <div class="data-group">
                    <div class="data-label">Gas</div>
                    <div class="data-value">${formatNum(actualGas)} m³</div>
                </div>
                <div class="data-group">
                    <div class="data-label">Electricity</div>
                    <div class="data-value">${formatNum(actualElec)} kWh</div>
                </div>
                <div class="data-group">
                    <div class="data-label">PV Yield</div>
                    <div class="data-value">${formatNum(actualPV)} kWh</div>
                </div>
            </div>

            <div class="data-column sim-column ${simActiveClass}" id="sim-col">
                <div class="column-header">Simulated</div>
                <div class="data-group">
                    <div class="data-label">Gas</div>
                    <div class="data-value sim-value" id="val-sim-gas">${formatNum(scenarioGas)} m³</div>
                </div>
                <div class="data-group">
                    <div class="data-label">Electricity</div>
                    <div class="data-value sim-value" id="val-sim-elec">${formatNum(scenarioElec)} kWh</div>
                </div>
                <div class="data-group">
                    <div class="data-label">PV Yield</div>
                    <div class="data-value sim-value" id="val-sim-pv">${formatNum(scenarioPV)} kWh</div>
                </div>
            </div>
        </div>

        <div style="margin-top:40px; font-size:9px; color:var(--text-muted); line-height:1.5;">
            <strong>METHODOLOGY</strong><br>
            Geometry: CBS 2021 PC6 Boundaries.<br>
            Energy: VNG (CBS) Energy Statistics 2023.<br>
            Source: ${sourceLabel}.
        </div>

        <div class="feature-quality" data-level="${completeness}">
            <span class="quality-score">${completeness}/3</span>
            <span><strong>Datacompleetheid</strong><br>${completenessLabel}</span>
        </div>
    `;

}

function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, (character) => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    })[character]);
}

function updatePvSidePanel(prop) {
    const formatNum = (value) => Number(value || 0).toLocaleString('nl-NL', {
        maximumFractionDigits: 1
    });
    const completeness = Number(prop.datacompleetheid ?? 0);
    const label = escapeHtml(prop.datacompleetheid_label || 'not assessed');
    const reason = escapeHtml(prop.completeness_reason || 'No quality explanation available.');
    if (prop.cbs_buurt_code) {
        selectTransformerProfileSource({
            type: 'cbs_buurt',
            id: prop.cbs_buurt_code,
            label: prop.buurt_name || prop.cbs_buurt_code
        });
    }

    document.getElementById('panel-content').innerHTML = `
        <div class="pc6-header">${escapeHtml(prop.buurt_name)}</div>
        <div class="feature-identifier">${escapeHtml(prop.cbs_buurt_code)}</div>

        <div class="data-grid pv-capacity-grid">
            <div class="data-column">
                <div class="column-header">Installed capacity</div>
                <div class="data-group">
                    <div class="data-label">Combined estimate</div>
                    <div class="data-value">${formatNum(prop.pv_capacity_kwp)} kWp</div>
                </div>
                <div class="data-group">
                    <div class="data-label">Residential</div>
                    <div class="data-value">${formatNum(prop.residential_kwp_real)} kWp</div>
                </div>
                <div class="data-group">
                    <div class="data-label">Commercial</div>
                    <div class="data-value">${formatNum(prop.commercial_kwp_derived)} kWp</div>
                </div>
            </div>
        </div>

        <div class="feature-quality" data-level="${completeness}" title="${reason}">
            <span class="quality-score">${completeness}/3</span>
            <span><strong>Datacompleetheid</strong><br>${label}</span>
        </div>

        <div class="pv-provenance">
            <strong>MODEL-ESTIMATED PV CAPACITY</strong><br>
            Source period: ${escapeHtml(prop.source_reference_period)}<br>
            Model version: ${escapeHtml(prop.model_version)}<br>
            <a href="/models/pv/metadata" target="_blank" rel="noopener">Model metadata</a>
        </div>
    `;
}

function qualityMarkup(prop) {
    const completeness = Number(prop.datacompleetheid ?? 0);
    const label = escapeHtml(prop.datacompleetheid_label || 'not assessed');
    const summary = escapeHtml(
        prop.datacompleetheid_summary || prop.completeness_reason ||
            prop.quality_evidence?.summary || 'No quality explanation available.'
    );
    return `
        <div class="feature-quality" data-level="${completeness}" title="${summary}">
            <span class="quality-score">${completeness}/3</span>
            <span><strong>Datacompleetheid</strong><br>${label}</span>
        </div>
    `;
}

function updateEvSidePanel(prop) {
    const formatNum = (value, digits = 0) => value == null
        ? 'Unknown'
        : Number(value).toLocaleString('nl-NL', { maximumFractionDigits: digits });
    document.getElementById('panel-content').innerHTML = `
        <div class="pc6-header">Public EV charger</div>
        <div class="feature-identifier">${escapeHtml(prop.address || prop.source_feature_id)}</div>
        <div class="data-grid grid-component-grid">
            <div class="data-column">
                <div class="data-group">
                    <div class="data-label">Operator</div>
                    <div class="data-value">${escapeHtml(prop.operator_name || 'Unknown')}</div>
                </div>
                <div class="data-group">
                    <div class="data-label">Connectors</div>
                    <div class="data-value">${formatNum(prop.available_connector_count)} / ${formatNum(prop.connector_count)} available</div>
                </div>
                <div class="data-group">
                    <div class="data-label">Maximum connector power</div>
                    <div class="data-value">${formatNum(prop.max_power_kw, 1)} kW</div>
                </div>
                <div class="data-group">
                    <div class="data-label">Modelled annual demand</div>
                    <div class="data-value">${formatNum(prop.modeled_annual_energy_kwh)} kWh</div>
                </div>
                <div class="data-group">
                    <div class="data-label">Modelled annual peak</div>
                    <div class="data-value">${formatNum(prop.modeled_annual_peak_kw, 1)} kW</div>
                </div>
            </div>
        </div>
        ${qualityMarkup(prop)}
        <div class="pv-provenance">
            <strong>PUBLIC CHARGER INVENTORY</strong><br>
            Profile: ${prop.profile_available ? 'PT15M profile available' : 'No profile available'}<br>
            Model version: ${escapeHtml(prop.model_version)}<br>
            <a href="/models/ev/metadata" target="_blank" rel="noopener">Model metadata</a>
        </div>
    `;
}

function updateConsumptionSidePanel(prop) {
    const formatEnergy = (value) => value == null
        ? 'Not available at this spatial level'
        : `${Number(value).toLocaleString('nl-NL', { maximumFractionDigits: 0 })} kWh/year`;
    const unitType = String(prop.spatial_unit_type || '').toUpperCase();
    document.getElementById('panel-content').innerHTML = `
        <div class="pc6-header">${escapeHtml(prop.name)}</div>
        <div class="feature-identifier">${escapeHtml(prop.spatial_unit_code)} · ${escapeHtml(unitType)}</div>
        <div class="data-grid consumption-grid">
            <div class="data-column">
                <div class="column-header">Annual electricity</div>
                <div class="data-group">
                    <div class="data-label">Combined</div>
                    <div class="data-value">${formatEnergy(
                        prop.annual_electricity_consumption_kwh ?? prop.annual_electricity_kwh
                    )}</div>
                </div>
                <div class="data-group">
                    <div class="data-label">Residential</div>
                    <div class="data-value">${formatEnergy(prop.residential_electricity_kwh)}</div>
                </div>
                <div class="data-group">
                    <div class="data-label">Business</div>
                    <div class="data-value">${formatEnergy(prop.business_electricity_kwh)}</div>
                </div>
                <div class="data-group">
                    <div class="data-label">Services / commerce</div>
                    <div class="data-value">${formatEnergy(prop.services_commerce_electricity_kwh)}</div>
                </div>
                <div class="data-group">
                    <div class="data-label">Unknown industrial / business</div>
                    <div class="data-value">${formatEnergy(prop.unknown_industrial_business_electricity_kwh)}</div>
                </div>
            </div>
        </div>
        ${qualityMarkup(prop)}
        <div class="pv-provenance">
            <strong>CONSUMPTION MODEL</strong><br>
            Reference period: ${escapeHtml(prop.source_reference_period)}<br>
            Spatial allocation: ${escapeHtml(prop.allocation_method)}<br>
            <a href="/models/consumption/metadata" target="_blank" rel="noopener">Model metadata</a>
        </div>
    `;
}

function updateGridLineSidePanel(prop) {
    const length = prop.length_km == null
        ? 'Unknown'
        : `${Number(prop.length_km).toLocaleString('nl-NL', { maximumFractionDigits: 3 })} km`;
    document.getElementById('panel-content').innerHTML = `
        <div class="pc6-header">Grid line</div>
        <div class="feature-identifier">${escapeHtml(prop.component_id)}</div>
        <div class="data-grid grid-component-grid">
            <div class="data-column">
                <div class="data-group">
                    <div class="data-label">Voltage level</div>
                    <div class="data-value">${escapeHtml(String(prop.voltage_level).toUpperCase())}</div>
                </div>
                <div class="data-group">
                    <div class="data-label">Component type</div>
                    <div class="data-value">${escapeHtml(prop.component_type)}</div>
                </div>
                <div class="data-group">
                    <div class="data-label">Length</div>
                    <div class="data-value">${escapeHtml(length)}</div>
                </div>
                <div class="data-group">
                    <div class="data-label">Serving transformer</div>
                    <div class="data-value compact-value">${escapeHtml(prop.serving_transformer_id || 'Not uniquely assigned')}</div>
                </div>
            </div>
        </div>
        ${qualityMarkup(prop)}
        <div class="pv-provenance">
            <strong>GRID TOPOLOGY SNAPSHOT</strong><br>
            Evidence: ${escapeHtml(prop.evidence_status)}<br>
            Grid data: ${escapeHtml(prop.grid_data_version)}<br>
            <a href="/models/grid/metadata" target="_blank" rel="noopener">Model metadata</a>
        </div>
    `;
}

function gridVoedingsgebieden() {
    return [...voedingsgebiedColors.keys()];
}

function formatMw(value) {
    return value == null
        ? 'Niet gepubliceerd'
        : `${Number(value).toLocaleString('nl-NL', { maximumFractionDigits: 1 })} MW`;
}

function capacityDirectionMarkup(prop, direction, label) {
    return `
        <div class="data-column">
            <div class="data-group">
                <div class="data-label">${label}: voedingsgebied</div>
                <div class="data-value compact-value">${escapeHtml(prop[`${direction}_service_area_name`] || 'Geen')}</div>
            </div>
            <div class="data-group">
                <div class="data-label">Bestaande / benodigde transportcapaciteit</div>
                <div class="data-value">${escapeHtml(formatMw(prop[`existing_transport_capacity_${direction}_mw`]))} / ${escapeHtml(formatMw(prop[`required_transport_capacity_${direction}_mw`]))}</div>
            </div>
            <div class="data-group">
                <div class="data-label">Wachtrij</div>
                <div class="data-value">${escapeHtml(formatMw(prop[`queue_${direction}_mw`]))} (${escapeHtml(prop[`unique_requests_${direction}`] ?? '?')} aanvragen)</div>
            </div>
            <div class="data-group">
                <div class="data-label">Verwacht opgelost (RNB / TenneT)</div>
                <div class="data-value">${escapeHtml(prop[`year_solved_${direction}`] || '?')} / ${escapeHtml(prop[`tennet_year_solved_${direction}`] || '?')}</div>
            </div>
        </div>
    `;
}

function updateGridCapacitySidePanel(prop) {
    selectScenarioTargetByPc6(prop.pc6_id);
    const available = prop.assignment_status === 'available';
    const congestionLink = prop.congestion_url && /^https:\/\//.test(prop.congestion_url)
        ? `<a href="${escapeHtml(prop.congestion_url)}" target="_blank" rel="noopener">Congestie-informatie ${escapeHtml(prop.rnb || '')}</a><br>`
        : '';
    document.getElementById('panel-content').innerHTML = `
        <div class="pc6-header">${escapeHtml(prop.pc6_id)}</div>
        <div class="feature-identifier">Voedingsgebied (capaciteitskaart)</div>
        ${available ? `
        <div class="data-grid grid-component-grid">
            ${capacityDirectionMarkup(prop, 'withdrawal', 'Afname')}
            ${capacityDirectionMarkup(prop, 'injection', 'Teruglevering')}
        </div>` : `
        <div class="compact-value">EDSN publiceert voor deze postcode geen voedingsgebied.</div>`}
        ${qualityMarkup(prop)}
        <div class="pv-provenance">
            <strong>EDSN CAPACITEITSKAART</strong><br>
            Netbeheerder: ${escapeHtml(prop.rnb || 'onbekend')}<br>
            Referentieperiode: ${escapeHtml(prop.source_reference_period || '?')}<br>
            ${congestionLink}
            Grid data: ${escapeHtml(prop.grid_data_version)}<br>
            <a href="/models/grid/metadata" target="_blank" rel="noopener">Model metadata</a>
        </div>
    `;
}

function updateWindTurbineSidePanel(prop) {
    const capacity = prop.capacity_kw == null
        ? 'Unknown'
        : `${Number(prop.capacity_kw).toLocaleString('nl-NL')} kW`;
    const annualEnergy = prop.modeled_annual_energy_kwh == null
        ? 'Not available'
        : `${Math.round(Number(prop.modeled_annual_energy_kwh)).toLocaleString('nl-NL')} kWh`;
    const capacityFactor = prop.modeled_capacity_factor == null
        ? 'Not available'
        : `${(Number(prop.modeled_capacity_factor) * 100).toFixed(1)}%`;
    document.getElementById('panel-content').innerHTML = `
        <div class="pc6-header">Wind turbine</div>
        <div class="feature-identifier">${escapeHtml(prop.feature_id)}</div>
        <div class="data-grid grid-component-grid">
            <div class="data-column">
                <div class="data-group">
                    <div class="data-label">Published capacity</div>
                    <div class="data-value">${escapeHtml(capacity)}</div>
                </div>
                <div class="data-group">
                    <div class="data-label">Hub / rotor</div>
                    <div class="data-value">${escapeHtml(prop.hub_height_m ?? '?')} / ${escapeHtml(prop.rotor_diameter_m ?? '?')} m</div>
                </div>
                <div class="data-group">
                    <div class="data-label">Provisional 2025 energy</div>
                    <div class="data-value compact-value">${escapeHtml(annualEnergy)}</div>
                </div>
                <div class="data-group">
                    <div class="data-label">Capacity factor</div>
                    <div class="data-value">${escapeHtml(capacityFactor)}</div>
                </div>
            </div>
        </div>
        ${qualityMarkup(prop)}
        <div class="pv-provenance">
            <strong>WIND INVENTORY AND PROVISIONAL MODEL</strong><br>
            Source period: ${escapeHtml(prop.source_reference_period || 'Unknown')}<br>
            Profile transport: ${prop.profile_transport_available ? 'Available' : 'Not yet available'}<br>
            <a href="/models/wind/metadata" target="_blank" rel="noopener">Model metadata</a>
        </div>
    `;
}

function formatHeatValue(value, unit) {
    if (value === null || value === undefined || value === '') return 'Not available';
    const rendered = typeof value === 'number'
        ? value.toLocaleString('nl-NL', { maximumFractionDigits: 2 })
        : String(value).replaceAll('_', ' ');
    return `${rendered}${unit}`;
}

function updateHeatSidePanel(layerId, prop) {
    const config = HEAT_LAYER_UI[layerId];
    const rows = config.fields.map(([field, label, unit]) => `
        <div class="data-group">
            <div class="data-label">${escapeHtml(label)}</div>
            <div class="data-value compact-value">${escapeHtml(formatHeatValue(prop[field], unit))}</div>
        </div>
    `).join('');
    const evidenceStatus = String(prop.evidence_status || 'Not available').replaceAll('_', ' ');
    document.getElementById('panel-content').innerHTML = `
        <div class="pc6-header">${escapeHtml(config.title)}</div>
        <div class="feature-identifier">${escapeHtml(prop.feature_id)}</div>
        <div class="data-grid grid-component-grid">
            <div class="data-column">${rows}</div>
        </div>
        ${qualityMarkup(prop)}
        <div class="pv-provenance">
            <strong>HEAT-NET-MAP EVIDENCE</strong><br>
            Evidence: ${escapeHtml(evidenceStatus)}<br>
            Snapshot: ${escapeHtml(prop.model_snapshot_id || 'Unknown')}<br>
            <a href="/models/heat/metadata" target="_blank" rel="noopener">Model metadata</a>
        </div>
    `;
}

function refreshVisuals(originalProps) {
    // This forces Leaflet to re-calculate the styles and patterns
    if (pc6Layer) pc6Layer.setStyle(style);

    const simulatedColumn = document.getElementById('sim-col');
    if (!simulatedColumn) return;
    simulatedColumn.classList.add('active');
    
    const scenarioGas = getCalculatedValue({properties: originalProps}, 'gas');
    const scenarioElec = getCalculatedValue({properties: originalProps}, 'elec');
    const scenarioPV = getCalculatedValue({properties: originalProps}, 'pv');
    const formatNum = (val) => Math.round(val).toLocaleString('nl-NL');
    
    document.getElementById('val-sim-gas').innerText = formatNum(scenarioGas) + " m³";
    document.getElementById('val-sim-elec').innerText = formatNum(scenarioElec) + " kWh";
    document.getElementById('val-sim-pv').innerText = formatNum(scenarioPV) + " kWh";
}

// Keep your listeners but ensure they are correctly mapped
document.getElementById('search-btn').addEventListener('click', searchPostcode);
document.getElementById('search-input').addEventListener('keypress', (e) => {
    if (e.key === 'Enter') searchPostcode();
});

document.querySelectorAll('input[name="layer"]').forEach(radio => {
    radio.addEventListener('change', (e) => {
        currentMetric = e.target.value;
        setActiveMapLayer(true);
    });
});

document.querySelectorAll('#grid-visibility input[type="checkbox"]').forEach((checkbox) => {
    checkbox.addEventListener('change', () => {
        applyGridVisibility();
        updateLegend();
    });
});

document.querySelectorAll('[data-heat-view]').forEach((checkbox) => {
    checkbox.addEventListener('change', () => {
        applyHeatVisibility();
        refreshLayerStatus();
        updateLegend();
    });
});

let energyChart = null;
let transformerProfileChart = null;
let lastCsvData = null; // Store data to allow re-rendering in the popup

async function runPythonSimulation(postcode, scenario) {
    const btn = document.getElementById('run-sim-btn');
    const output = document.getElementById('simulation-output');
    const graphContainer = document.getElementById('graph-container');
    const titleElement = output.querySelector('.control-label');
    
    // UI Feedback: Start
    btn.innerText = "RUNNING BACKEND...";
    btn.disabled = true;

    scenarioRunning = true;
    // Sanitize inputs
    const pc6 = postcode.replace(/\s+/g, '').toUpperCase();
    const electrification = (1 - scenario.gas).toFixed(2);

    try {
        /* 1. CALL THE BACKEND API 
           Traefik routes /policy-api/ to your policy-tool-backend container.
           The backend runs the simulation and returns a success JSON.
        */
        const apiUrl = `/policy-api/simulate/${pc6}?electrification=${electrification}`;
        const apiResponse = await fetch(apiUrl);
        
        if (!apiResponse.ok) {
            const errorData = await apiResponse.json().catch(() => ({}));
            console.error("Backend failed:", errorData);
            throw new Error('BACKEND_ERROR');
        }

        const apiResult = await apiResponse.json();
        console.log("Backend simulation complete:", apiResult);

        /* 2. FETCH THE GENERATED FILE 
           The backend script writes to /app/data/processed/.
           Docker volume shares this with Frontend at /usr/share/nginx/html/dashboard/processed/.
           Since this JS is running at [hostname]/dashboard/, we use the relative path 'processed/'.
        */
        const filePath = `processed/pc6_profile_${pc6}.csv`;
        
        // Use a timestamp cache-buster to ensure we don't load an old version of the CSV
        const fileResponse = await fetch(`${filePath}?t=${new Date().getTime()}`);
        
        if (!fileResponse.ok) {
            console.error("File found in volume but failed to fetch:", filePath);
            throw new Error('FILE_SYNC_ERROR');
        }
        
        // Save to global variable (assuming lastCsvData is declared elsewhere)
        lastCsvData = await fileResponse.text();

        /* 3. UPDATE UI AND RENDER
           Update the title with the specific PC6 and Electrification level.
        */
        titleElement.innerHTML = `
            Result for ${pc6} (${Math.round(electrification * 100)}% Elec)
            <span class="expand-btn" onclick="openChartModal()" style="cursor:pointer; font-size: 1.2em; margin-left: 10px;">
                &#128464;
            </span>
        `;

        graphContainer.innerHTML = '<canvas id="chartCanvas"></canvas>';
            output.hidden = false;
            renderEnergyChart('chartCanvas', lastCsvData, false);

    } catch (err) {
        console.error("Simulation Flow Error:", err);
        alert(`Error: ${err.message === 'BACKEND_ERROR' ? 'The simulation script failed.' : 'Could not retrieve simulation results.'}`);
    } finally {
        // Reset UI state
        scenarioRunning = false;
        btn.innerText = "RUN SCENARIO";
        updateScenarioControls();
    }
}

// Reusable Charting Function
function renderEnergyChart(canvasId, csvData, isModal = false) {
    const rows = csvData.trim().split('\n').slice(1);
    const labels = [];
    const datasets = { gross: [], pv: [], net: [], heat: [], hp: [], gas: [] };

    rows.forEach(row => {
        const cols = row.split(',');
        labels.push(cols[0]); // timestamp
        datasets.gross.push(parseFloat(cols[1]));
        datasets.pv.push(parseFloat(cols[2]));
        datasets.net.push(parseFloat(cols[3]));
        datasets.heat.push(parseFloat(cols[4]));
        datasets.hp.push(parseFloat(cols[5]));
        datasets.gas.push(parseFloat(cols[6]));
    });

    const ctx = document.getElementById(canvasId).getContext('2d');
    
    // If it's the sidebar chart, destroy previous instance
    if (!isModal && energyChart) energyChart.destroy();

    const chartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                { label: 'Elec Gross', data: datasets.gross, borderColor: '#3498db', borderWidth: 1, pointRadius: 0 },
                { label: 'PV Gen', data: datasets.pv, borderColor: '#f1c40f', borderWidth: 1, pointRadius: 0 },
                { label: 'Elec Net', data: datasets.net, borderColor: '#2c3e50', borderWidth: 2, pointRadius: 0 },
                { label: 'Heat Demand', data: datasets.heat, borderColor: '#e67e22', borderWidth: 1, pointRadius: 0 },
                { label: 'HP Input', data: datasets.hp, borderColor: '#9b59b6', borderWidth: 1, pointRadius: 0 },
                { label: 'Gas Input', data: datasets.gas, borderColor: '#e74c3c', borderWidth: 1, pointRadius: 0 }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: {
                    type: 'time',
                    time: { unit: 'month', displayFormats: { month: 'M/yy' } },
                    min: '2026-01-01',
                    max: '2026-12-31',
                    ticks: { font: { size: isModal ? 11 : 8 } }
                }
            },
            plugins: {
                legend: { position: 'top', labels: { boxWidth: 10, font: { size: isModal ? 12 : 9 } } }
            }
        }
    });

    if (!isModal) energyChart = chartInstance;
    return chartInstance;
}

function openChartModal() {
    const modal = document.getElementById('chart-modal');
    const container = document.getElementById('modal-graph-container');
    const closeBtn = document.getElementById('close-modal-btn');

    modal.style.display = "block";
    container.innerHTML = '<canvas id="modalCanvas"></canvas>';
    
    // Slight delay to ensure canvas is ready in DOM
    setTimeout(() => renderEnergyChart('modalCanvas', lastCsvData, true), 50);

    // Define the Close Function
    const closeModal = () => {
        modal.style.display = "none";
        // Remove the keydown listener when modal is closed to save memory
        document.removeEventListener('keydown', handleEsc);
    };

    // Setup Exit Listeners (X and ESC)
    closeBtn.onclick = closeModal;

    const handleEsc = (e) => {
        if (e.key === "Escape") closeModal();
    };
    document.addEventListener('keydown', handleEsc);

    // Optional: Close on background click
    modal.onclick = (e) => {
        if (e.target === modal) closeModal();
    };
}

// Run
initializeScenarioControls();
initializeTransformerProfileControls();
loadMap();
