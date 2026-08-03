// Initialize Map
const map = L.map('map', { zoomControl: false }).setView([52.632, 4.753], 13);

L.control.zoom({ position: 'bottomleft' }).addTo(map);

// Add Base Layer
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '© OpenStreetMap',
    opacity: 0.85
}).addTo(map);

let pc6Layer;
let currentMetric = 'gas';
let pc6LayerSource = 'loading';

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

// Data Loading
function updateLayerStatus(source, fallbackReason = null) {
    const status = document.getElementById('layer-source-status');
    pc6LayerSource = source;
    status.dataset.state = source;
    status.textContent = source === 'geoserver_wfs'
        ? 'Live GeoServer WFS'
        : source === 'static_geojson'
            ? 'Static fallback active'
            : source === 'failed'
                ? 'Layer unavailable'
                : 'Loading layer';
    status.title = fallbackReason || '';
}

async function loadMap() {
    try {
        const result = await Pc6MapData.loadPc6FeatureCollection(fetch);
        const data = result.data;
        updateLayerStatus(result.source, result.fallbackReason);
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
        }).addTo(map);

        if (data.features.length > 0) {
            map.fitBounds(pc6Layer.getBounds());
        }
        updateLegend();

    } catch (e) {
        console.error("Data load failed:", e);
        updateLayerStatus('failed', e.message);
    }
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
        const grades = currentMetric === 'gas' ? [0, 400, 600, 800, 1000, 1200, 1500] : [0, 1500, 2000, 2500, 3000, 3500, 4000];
        const title = currentMetric === 'gas' ? 'GAS (m³)' : 'ELEC (kWh)';
        
        div.innerHTML = `<div style="margin-bottom:8px; font-weight:700; font-size:9px;">${title}</div>`;
        
        grades.forEach((g, i) => {
            div.innerHTML += `<i style="background:${getColor(g + 1, currentMetric)}"></i> ${g}${grades[i+1] ? '&ndash;'+grades[i+1] : '+'}<br>`;
        });
        return div;
    };
    legend.addTo(map);
}

// Global object to store local overrides
// Format: { "1811AA": { gas: 0.5, pv: 2.0 }, ... }
let postcodeScenarios = {};

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
    
    // Ensure the scenario object exists
    if (!postcodeScenarios[pc]) {
        postcodeScenarios[pc] = { gas: 1.0, pv: 1.0, modified: false };
    }
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

        <div class="sidebar-controls">
            <div class="control-label" style="margin-bottom:15px; color:var(--accent-red)">Local Scenario Parameters</div>
            <div class="slider-unit">
                <div class="slider-header">
                    <span class="slider-label">Gas Demand</span>
                    <span class="slider-pct" id="pct-gas">${Math.round(s.gas * 100)}%</span>
                </div>
                <input type="range" class="side-slider" id="input-gas" min="0" max="100" value="${s.gas * 100}">
            </div>

            <div class="slider-unit">
                <div class="slider-header">
                    <span class="slider-label">PV Adoption</span>
                    <span class="slider-pct" id="pct-pv">${Math.round(s.pv * 100)}%</span>
                </div>
                <input type="range" class="side-slider" id="input-pv" min="100" max="500" value="${s.pv * 100}">
            </div>

            <div class="simulation-actions" style="margin-top: 25px;">
                <button id="run-sim-btn" class="primary-btn">RUN POLICY SIMULATION</button>
            </div>

            <div id="simulation-output" style="margin-top: 20px; display: none;">
                <div class="control-label">Simulation Result</div>
                <div id="graph-container" style="width: 100%; height: 200px; background: #f9f9f9; border: 1px dashed #ccc; display: flex; align-items: center; justify-content: center; border-radius: 4px;">
                    <span style="font-size: 10px; color: #999;">Graph will render here...</span>
                </div>
                <a id="download-link" href="#" style="display: block; margin-top: 10px; font-size: 10px; color: var(--primary-dark); text-decoration: underline;">Download processed_data.csv</a>
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

    // Re-attach listeners because innerHTML wipes them
    document.getElementById('input-gas').addEventListener('input', (e) => {
        postcodeScenarios[pc].gas = e.target.value / 100;
        postcodeScenarios[pc].modified = true;
        document.getElementById('pct-gas').innerText = e.target.value + "%";
        refreshVisuals(prop);
    });

    document.getElementById('input-pv').addEventListener('input', (e) => {
        postcodeScenarios[pc].pv = e.target.value / 100;
        postcodeScenarios[pc].modified = true;
        document.getElementById('pct-pv').innerText = e.target.value + "%";
        refreshVisuals(prop);
    });

    document.getElementById('run-sim-btn').addEventListener('click', () => {
        runPythonSimulation(pc, postcodeScenarios[pc]);
    });
}

function refreshVisuals(originalProps) {
    // This forces Leaflet to re-calculate the styles and patterns
    pc6Layer.setStyle(style); 
    
    // ... update the numeric columns as before ...
    const pc = originalProps.postcode6;
    document.getElementById('sim-col').classList.add('active');
    
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
        if (pc6Layer) pc6Layer.setStyle(style);
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
            output.style.display = "block";
            renderEnergyChart('chartCanvas', lastCsvData, false);

    } catch (err) {
        console.error("Simulation Flow Error:", err);
        alert(`Error: ${err.message === 'BACKEND_ERROR' ? 'The simulation script failed.' : 'Could not retrieve simulation results.'}`);
    } finally {
        // Reset UI state
        btn.innerText = "RUN SIMULATION";
        btn.disabled = false;
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
loadMap();