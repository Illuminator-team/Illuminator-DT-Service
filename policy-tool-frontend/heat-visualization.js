(function (root, factory) {
    const api = factory();
    if (typeof module === 'object' && module.exports) {
        module.exports = api;
    }
    root.HeatVisualization = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    const POINT_COLORS = Object.freeze({
        documented_actual_heat_sources: '#cb181d',
        documented_large_heat_consumers: '#2171b5',
        potential_heat_sources: '#238b45'
    });

    function neighbourhoodColor(value) {
        const share = Number(value) || 0;
        return share >= 90 ? '#800026' : share >= 70 ? '#bd0026' :
            share >= 50 ? '#e31a1c' : share >= 35 ? '#fd8d3c' :
            share >= 20 ? '#feb24c' : share >= 10 ? '#fed976' : '#fff7bc';
    }

    function pc6Fill(properties) {
        const inferenceClass = String(properties.inference_class || '');
        const allocated = Number(properties.allocated_connected_dwellings_est) || 0;
        if (inferenceClass === 'excluded_possible_electric_heating') {
            return { fillColor: '#9e9ac8', fillOpacity: 0.32 };
        }
        if (allocated > 0 && inferenceClass.startsWith('strong_')) {
            return { fillColor: '#084594', fillOpacity: 0.62 };
        }
        if (allocated > 0 && inferenceClass.startsWith('moderate_')) {
            return { fillColor: '#4292c6', fillOpacity: 0.58 };
        }
        if (allocated > 0) {
            return { fillColor: '#c6dbef', fillOpacity: 0.7 };
        }
        if (inferenceClass.includes('low_gas_normal_electricity')) {
            return { fillColor: '#fdbb30', fillOpacity: 0.4 };
        }
        return { fillColor: '#d9d9d9', fillOpacity: 0.12 };
    }

    function pc6Outline(properties) {
        const status = String(properties.liander_crosscheck_status || '');
        if (status.startsWith('supports_')) {
            return { color: '#238b45', dashArray: null };
        }
        if (status.startsWith('conflicts_')) {
            return { color: '#cb181d', dashArray: null };
        }
        return { color: '#737373', dashArray: '5 4' };
    }

    function layerStyle(layerId, feature = {}) {
        const properties = feature.properties || {};
        if (layerId === 'reported_neighbourhood_heat_consumers') {
            return {
                color: '#7f2704',
                weight: 1.2,
                fillColor: neighbourhoodColor(properties.reported_connected_share_pct),
                fillOpacity: 0.62
            };
        }
        if (layerId === 'inferred_pc6_heat_consumers') {
            return { ...pc6Fill(properties), ...pc6Outline(properties), weight: 2.4 };
        }
        if (layerId === 'registered_heat_network_developments') {
            return {
                color: '#54278f',
                dashArray: '8 6',
                weight: 3,
                fillColor: '#756bb1',
                fillOpacity: 0.1
            };
        }
        const pointColor = POINT_COLORS[layerId] || '#4e606d';
        return {
            radius: 7,
            color: '#ffffff',
            weight: 2,
            fillColor: pointColor,
            fillOpacity: 0.95
        };
    }

    return Object.freeze({ neighbourhoodColor, pc6Fill, pc6Outline, layerStyle });
}));
