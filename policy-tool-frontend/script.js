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
let gridLineLayers = {};
let gridTransformerLayers = {};
let gridLvMvReachLayer;
let gridMvHvReachLayer;
let gridHasFit = false;
let currentMetric = 'gas';
let pc6LayerSource = 'loading';
let pvLayerSource = 'loading';
const gridLayerSources = {
    grid_lines: 'loading',
    grid_transformers: 'loading',
    grid_lv_mv_transformer_reach: 'loading',
    grid_mv_hv_transformer_reach: 'loading'
};
const gridCanvasRenderer = L.canvas({ padding: 0.5 });

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

function gridTransformerStyle(feature) {
    const isHighVoltage = feature.properties.transformer_type === 'mv_hv';
    return {
        radius: isHighVoltage ? 8 : 6,
        color: '#ffffff',
        weight: 2,
        fillColor: isHighVoltage ? '#e58c2c' : '#7651a8',
        fillOpacity: 0.95
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

function gridReachStyle(feature) {
    const properties = feature.properties || {};
    const color = getReachColor(
        properties.dominant_transformer_id || properties.component_id
    );
    return {
        color, weight: 2, opacity: 0.8, fillColor: color, fillOpacity: 0.18,
        dashArray: properties.is_ambiguous ? '5 4' : null
    };
}

// Data Loading
function renderLayerStatus(source, fallbackReason = null) {
    const status = document.getElementById('layer-source-status');
    status.dataset.state = source;
    status.textContent = source === 'geoserver_wfs'
        ? 'Live GeoServer WFS'
        : source === 'partial'
            ? 'Some Grid layers unavailable'
            : source === 'static_geojson'
                ? 'Static fallback active'
                : source === 'failed'
                    ? 'Layer unavailable'
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

function updateLayerStatus(layerName, source, fallbackReason = null) {
    if (layerName === 'pv_capacity') {
        pvLayerSource = source;
    } else if (Object.hasOwn(gridLayerSources, layerName)) {
        gridLayerSources[layerName] = source;
    } else {
        pc6LayerSource = source;
    }
    const activeLayer = ['gas', 'elec'].includes(currentMetric) ? 'pc6' : currentMetric;
    if (activeLayer === 'grid_network' && Object.hasOwn(gridLayerSources, layerName)) {
        renderLayerStatus(getGridNetworkSource(), fallbackReason);
    } else if (activeLayer === layerName) {
        renderLayerStatus(source, fallbackReason);
    }
}

function refreshLayerStatus() {
    const activeLayer = ['gas', 'elec'].includes(currentMetric) ? 'pc6' : currentMetric;
    const sources = {
        pc6: pc6LayerSource,
        pv_capacity: pvLayerSource,
        grid_network: getGridNetworkSource()
    };
    renderLayerStatus(sources[activeLayer]);
}

function updateLayerQualitySummary() {
    const label = document.getElementById('layer-quality-label');
    const meter = document.getElementById('layer-quality-meter');
    const isPvCapacity = currentMetric === 'pv_capacity';
    const isGrid = currentMetric === 'grid_network';
    label.textContent = isGrid
        ? 'Datacompleetheid per component'
        : isPvCapacity ? 'Datacompleetheid 1-2/3' : 'Datacompleetheid 2/3';
    meter.title = (isPvCapacity || isGrid)
        ? 'Feature-level confidence varies across this layer'
        : 'Layer-level confidence';
}

function gridControlChecked(id) {
    return Boolean(document.getElementById(id)?.checked);
}

function allGridLayers() {
    return [
        ...Object.values(gridLineLayers),
        gridLvMvReachLayer,
        ...Object.values(gridTransformerLayers),
        gridMvHvReachLayer
    ].filter(Boolean);
}

function selectedGridLayers() {
    const layers = [];
    if (gridControlChecked('grid-lv-mv-reach') && gridLvMvReachLayer) layers.push(gridLvMvReachLayer);
    if (gridControlChecked('grid-mv-hv-reach') && gridMvHvReachLayer) layers.push(gridMvHvReachLayer);
    if (gridControlChecked('grid-lv-lines') && gridLineLayers.lv) layers.push(gridLineLayers.lv);
    if (gridControlChecked('grid-mv-lines') && gridLineLayers.mv) layers.push(gridLineLayers.mv);
    if (gridControlChecked('grid-hv-lines') && gridLineLayers.hv) layers.push(gridLineLayers.hv);
    if (gridControlChecked('grid-lv-mv-transformers') && gridTransformerLayers.lv_mv) layers.push(gridTransformerLayers.lv_mv);
    if (gridControlChecked('grid-mv-hv-transformers') && gridTransformerLayers.mv_hv) layers.push(gridTransformerLayers.mv_hv);
    return layers;
}

function applyGridVisibility(fit = false) {
    allGridLayers().forEach((layer) => {
        if (map.hasLayer(layer)) map.removeLayer(layer);
    });
    if (currentMetric !== 'grid_network') return;

    const visibleLayers = selectedGridLayers();
    visibleLayers.forEach((layer) => layer.addTo(map));
    Object.values(gridLineLayers).forEach((layer) => {
        if (map.hasLayer(layer) && layer.bringToFront) layer.bringToFront();
    });
    Object.values(gridTransformerLayers).forEach((layer) => {
        if (map.hasLayer(layer) && layer.bringToFront) layer.bringToFront();
    });
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

function setActiveMapLayer(fitActive = false) {
    const activeLayerName = ['gas', 'elec'].includes(currentMetric) ? 'pc6' : currentMetric;
    [[pc6Layer, 'pc6'], [pvLayer, 'pv_capacity']].forEach(([layer, layerName]) => {
        if (layer && layerName !== activeLayerName && map.hasLayer(layer)) {
            map.removeLayer(layer);
        }
    });
    applyGridVisibility(fitActive || (currentMetric === 'grid_network' && !gridHasFit));

    const activeLayer = activeLayerName === 'pc6' ? pc6Layer : activeLayerName === 'pv_capacity' ? pvLayer : null;
    if (activeLayer && !map.hasLayer(activeLayer)) {
        activeLayer.addTo(map);
        if (activeLayerName !== 'pc6') map.fitBounds(activeLayer.getBounds());
    }
    if (activeLayerName === 'pc6' && pc6Layer) pc6Layer.setStyle(style);
    updateGridVisibilityPanel();
    refreshLayerStatus();
    updateLayerQualitySummary();
    updateLegend();
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
        const result = await Pc6MapData.loadGridLinesFeatureCollection(fetch);
        ['lv', 'mv', 'hv'].forEach((voltageLevel) => {
            gridLineLayers[voltageLevel] = L.geoJSON(result.data, {
                renderer: gridCanvasRenderer,
                filter: (feature) => feature.properties.voltage_level === voltageLevel,
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
        });
        updateLayerStatus('grid_lines', result.source);
    } catch (error) {
        console.error('Grid lines data load failed:', error);
        updateLayerStatus('grid_lines', 'failed', error.message);
        ['grid-lv-lines', 'grid-mv-lines', 'grid-hv-lines'].forEach((id) => {
            const control = document.getElementById(id);
            control.disabled = true;
            control.parentElement.title = 'Grid lines layer is unavailable';
        });
    }

    try {
        const result = await Pc6MapData.loadGridTransformersFeatureCollection(fetch);
        ['lv_mv', 'mv_hv'].forEach((transformerType) => {
            gridTransformerLayers[transformerType] = L.geoJSON(result.data, {
                filter: (feature) => feature.properties.transformer_type === transformerType,
                pointToLayer: (feature, latlng) => L.circleMarker(
                    latlng,
                    gridTransformerStyle(feature)
                ),
                onEachFeature: (feature, layer) => {
                    layer.on({
                        mouseover: (event) => event.target.setStyle({ weight: 4 }),
                        mouseout: (event) => event.target.setStyle(gridTransformerStyle(feature)),
                        click: (event) => {
                            updateGridTransformerSidePanel(feature.properties);
                            map.setView(event.target.getLatLng(), Math.max(map.getZoom(), 17));
                        }
                    });
                }
            });
        });
        updateLayerStatus('grid_transformers', result.source);
    } catch (error) {
        console.error('Grid transformer data load failed:', error);
        updateLayerStatus('grid_transformers', 'failed', error.message);
        ['grid-lv-mv-transformers', 'grid-mv-hv-transformers'].forEach((id) => {
            const control = document.getElementById(id);
            control.disabled = true;
            control.parentElement.title = 'Grid transformer layer is unavailable';
        });
    }
    try {
        const result = await Pc6MapData.loadGridLvMvReachFeatureCollection(fetch);
        gridLvMvReachLayer = L.geoJSON(result.data, {
            renderer: gridCanvasRenderer,
            style: gridReachStyle,
            onEachFeature: (feature, layer) => {
                layer.on({
                    mouseover: (event) => event.target.setStyle({ weight: 4, fillOpacity: 0.22 }),
                    mouseout: (event) => event.target.setStyle(gridReachStyle(feature)),
                    click: (event) => {
                        updateGridReachSidePanel(feature.properties, 'LV/MV');
                        map.fitBounds(event.target.getBounds(), { padding: [40, 40] });
                    }
                });
            }
        });
        updateLayerStatus('grid_lv_mv_transformer_reach', result.source);
    } catch (error) {
        console.error('Grid LV/MV transformer reach load failed:', error);
        updateLayerStatus('grid_lv_mv_transformer_reach', 'failed', error.message);
        const control = document.getElementById('grid-lv-mv-reach');
        control.disabled = true;
        control.parentElement.title = 'LV/MV transformer reach layer is unavailable';
    }


    try {
        const result = await Pc6MapData.loadGridMvHvReachFeatureCollection(fetch);
        gridMvHvReachLayer = L.geoJSON(result.data, {
            renderer: gridCanvasRenderer,
            style: gridReachStyle,
            onEachFeature: (feature, layer) => {
                layer.on({
                    mouseover: (event) => event.target.setStyle({ weight: 4, fillOpacity: 0.22 }),
                    mouseout: (event) => event.target.setStyle(gridReachStyle(feature)),
                    click: (event) => {
                        updateGridReachSidePanel(feature.properties, 'MV/HV');
                        map.fitBounds(event.target.getBounds(), { padding: [40, 40] });
                    }
                });
            }
        });
        updateLayerStatus('grid_mv_hv_transformer_reach', result.source);
    } catch (error) {
        console.error('Grid MV/HV transformer reach load failed:', error);
        updateLayerStatus('grid_mv_hv_transformer_reach', 'failed', error.message);
        const control = document.getElementById('grid-mv-hv-reach');
        control.disabled = true;
        control.parentElement.title = 'MV/HV transformer reach layer is unavailable';
    }

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
            const entries = [
                ['grid-lv-lines', '#c43d4f', 'LV lines'],
                ['grid-mv-lines', '#2378a7', 'MV lines'],
                ['grid-hv-lines', '#24292e', 'HV lines'],
                ['grid-lv-mv-transformers', '#7651a8', 'LV / MV transformers'],
                ['grid-mv-hv-transformers', '#e58c2c', 'MV / HV transformers'],
                ['grid-lv-mv-reach', '#7a4c9f', 'LV / MV reach (PC6 shares)'],
                ['grid-mv-hv-reach', '#16845b', 'MV / HV reach (PC6 shares)']
            ];
            entries.filter(([id]) => gridControlChecked(id)).forEach(([, color, label]) => {
                div.innerHTML += `<i style="background:${color}"></i> ${label}<br>`;
            });
            if (selectedGridLayers().length === 0) {
                div.innerHTML += 'No grid components selected';
            }
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
        prop.datacompleetheid_summary || 'No quality explanation available.'
    );
    return `
        <div class="feature-quality" data-level="${completeness}" title="${summary}">
            <span class="quality-score">${completeness}/3</span>
            <span><strong>Datacompleetheid</strong><br>${label}</span>
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

function updateGridTransformerSidePanel(prop) {
    const rating = prop.rated_power_kva == null
        ? 'Unknown'
        : `${Number(prop.rated_power_kva).toLocaleString('nl-NL')} kVA`;
    document.getElementById('panel-content').innerHTML = `
        <div class="pc6-header">Grid transformer</div>
        <div class="feature-identifier">${escapeHtml(prop.component_id)}</div>
        <div class="data-grid grid-component-grid">
            <div class="data-column">
                <div class="data-group">
                    <div class="data-label">Transformer type</div>
                    <div class="data-value">${escapeHtml(String(prop.transformer_type).toUpperCase())}</div>
                </div>
                <div class="data-group">
                    <div class="data-label">Rated power</div>
                    <div class="data-value">${escapeHtml(rating)}</div>
                </div>
                <div class="data-group">
                    <div class="data-label">Primary / secondary</div>
                    <div class="data-value">${escapeHtml(prop.primary_nominal_voltage_kv ?? '?')} / ${escapeHtml(prop.secondary_nominal_voltage_kv ?? '?')} kV</div>
                </div>
            </div>
        </div>
        ${qualityMarkup(prop)}
        <div class="pv-provenance">
            <strong>GRID TOPOLOGY SNAPSHOT</strong><br>
            Grid data: ${escapeHtml(prop.grid_data_version)}<br>
            <a href="/models/grid/metadata" target="_blank" rel="noopener">Model metadata</a>
        </div>
    `;
}

function parseReachShares(value) {
    if (Array.isArray(value)) return value;
    if (typeof value !== 'string' || value.length === 0) return [];
    try {
        const parsed = JSON.parse(value);
        return Array.isArray(parsed) ? parsed : [];
    } catch (error) {
        console.warn('Invalid ranked transformer shares:', error);
        return [];
    }
}

function formatReachShare(value) {
    if (value == null || value === '') return 'Not applicable';
    const numeric = Number(value);
    return Number.isFinite(numeric)
        ? `${numeric.toLocaleString('nl-NL', { maximumFractionDigits: 1 })}%`
        : 'Not applicable';
}

function updateGridReachSidePanel(prop, level) {
    const shares = parseReachShares(prop.ranked_shares ?? prop.ranked_shares_json);
    selectScenarioTargetByPc6(prop.pc6_id);
    const dominantName = prop.dominant_transformer_name || prop.dominant_transformer_id;
    const runnerUpName = prop.runner_up_transformer_name || prop.runner_up_transformer_id;
    const matchedLength = prop.matched_lv_cable_length_m == null
        ? 'Not available'
        : `${Number(prop.matched_lv_cable_length_m).toLocaleString('nl-NL', {
            maximumFractionDigits: 1
        })} m`;
    const evidence = prop.fallback_used
        ? `Nearest LV bus (${Number(prop.fallback_distance_m || 0).toLocaleString('nl-NL', {
            maximumFractionDigits: 1
        })} m)`
        : 'LV cable length inside PC6';
    const ambiguity = prop.is_ambiguous
        ? 'Close result'
        : prop.has_overlap ? 'Multiple shares, clear leader' : 'Single transformer';
    const sharesMarkup = shares.map((share) => `
        <div class="reach-share-row">
            <span>${escapeHtml(share.transformer_name || share.transformer_id)}</span>
            <strong>${formatReachShare(share.share_percent)}</strong>
        </div>
    `).join('');

    document.getElementById('panel-content').innerHTML = `
        <div class="pc6-header">${escapeHtml(prop.pc6_id)}</div>
        <div class="feature-identifier">${escapeHtml(level)} transformer reach</div>
        <div class="data-grid grid-component-grid">
            <div class="data-column">
                <div class="data-group">
                    <div class="data-label">Dominant transformer</div>
                    <div class="data-value compact-value">${escapeHtml(dominantName)}</div>
                    <div class="share-value">${formatReachShare(prop.dominant_transformer_share_percent)}</div>
                </div>
                <div class="data-group">
                    <div class="data-label">Runner-up</div>
                    <div class="data-value compact-value">${escapeHtml(runnerUpName || 'None')}</div>
                    <div class="share-value">${formatReachShare(prop.runner_up_transformer_share_percent)}</div>
                </div>
                <div class="data-group">
                    <div class="data-label">Assignment evidence</div>
                    <div class="data-value compact-value">${escapeHtml(evidence)}</div>
                </div>
                <div class="data-group">
                    <div class="data-label">Matched LV cable</div>
                    <div class="data-value">${escapeHtml(matchedLength)}</div>
                </div>
                <div class="data-group">
                    <div class="data-label">Share confidence</div>
                    <div class="data-value compact-value">${escapeHtml(ambiguity)}</div>
                </div>
            </div>
        </div>
        <div class="reach-shares">
            <div class="data-label">All absolute PC6 shares</div>
            ${sharesMarkup || '<div class="compact-value">No share breakdown available</div>'}
        </div>
        ${qualityMarkup(prop)}
        <div class="pv-provenance">
            <strong>PC6-BASED MODEL ASSIGNMENT</strong><br>
            ${escapeHtml(level)} shares are direct fractions of the original PC6 polygon.<br>
            Grid data: ${escapeHtml(prop.grid_data_version)}<br>
            <a href="/models/grid/metadata" target="_blank" rel="noopener">Model metadata</a>
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

let energyChart = null; 
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
loadMap();
