(function (root, factory) {
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    root.TransformerProfiles = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    'use strict';

    const STAGES = Object.freeze({
        lv_mv: Object.freeze({
            key: 'source_to_lv_mv',
            label: 'LV/MV',
            transformerLevel: 'lv_mv_transformer'
        }),
        mv_hv: Object.freeze({
            key: 'lv_mv_to_mv_hv',
            label: 'MV/HV',
            transformerLevel: 'mv_hv_transformer'
        })
    });

    const SOURCES = Object.freeze({
        pc6: Object.freeze({
            year: 2023,
            defaultDate: '2023-01-01',
            idPattern: /^\d{4}[A-Z]{2}$/,
            path: (id) => `/policy-api/transformer-profiles/pc6/${encodeURIComponent(id)}`
        }),
        cbs_buurt: Object.freeze({
            year: 2024,
            defaultDate: '2024-06-01',
            idPattern: /^BU\d{8}$/,
            path: (id) => (
                `/policy-api/transformer-profiles/pv/cbs-buurt/${encodeURIComponent(id)}`
            )
        })
    });

    function requireObject(value, message) {
        if (!value || typeof value !== 'object' || Array.isArray(value)) {
            throw new Error(message);
        }
        return value;
    }

    function normalizeSource(source) {
        requireObject(source, 'A transformer profile source is required.');
        const definition = SOURCES[source.type];
        const id = String(source.id || '').replace(/\s+/g, '').toUpperCase();
        if (!definition || !definition.idPattern.test(id)) {
            throw new Error('The selected feature is not a supported profile source.');
        }
        return {
            type: source.type,
            id,
            label: String(source.label || id),
            year: definition.year,
            defaultDate: definition.defaultDate
        };
    }

    function dayWindow(date, expectedYear) {
        if (!/^\d{4}-\d{2}-\d{2}$/.test(String(date || ''))) {
            throw new Error('Select a valid profile date.');
        }
        const start = new Date(`${date}T00:00:00Z`);
        if (Number.isNaN(start.getTime()) || start.getUTCFullYear() !== expectedYear) {
            throw new Error(`The profile date must be in ${expectedYear}.`);
        }
        const normalizedDate = start.toISOString().slice(0, 10);
        if (normalizedDate !== date) throw new Error('Select a valid profile date.');
        const end = new Date(start.getTime() + 24 * 60 * 60 * 1000);
        return {
            start: start.toISOString().replace('.000Z', 'Z'),
            end: end.toISOString().replace('.000Z', 'Z')
        };
    }

    function buildRequest(source, date) {
        const normalized = normalizeSource(source);
        const definition = SOURCES[normalized.type];
        return {
            source: normalized,
            url: definition.path(normalized.id),
            body: dayWindow(date, definition.year)
        };
    }

    function finiteNumber(value, field) {
        const number = Number(value);
        if (!Number.isFinite(number)) throw new Error(`Invalid transformer point ${field}.`);
        return number;
    }

    function normalizePoint(point) {
        requireObject(point, 'Transformer profile points must be objects.');
        const timestamp = String(point.interval_start_utc || '');
        if (!timestamp || Number.isNaN(Date.parse(timestamp))) {
            throw new Error('Transformer profile point has an invalid timestamp.');
        }
        const demand = finiteNumber(point.demand_power_kw, 'demand_power_kw');
        const production = finiteNumber(point.production_power_kw, 'production_power_kw');
        const net = finiteNumber(point.net_power_kw, 'net_power_kw');
        if (Math.abs(demand + production - net) > 1e-6) {
            throw new Error('Transformer profile point violates the canonical net-power sum.');
        }
        return {
            timestamp,
            demandPowerKw: demand,
            productionPowerKw: production,
            netPowerKw: net
        };
    }

    function normalizeTarget(target, stage) {
        requireObject(target, `${stage.label} transformer target must be an object.`);
        const id = String(target.transformer_id || '');
        if (!id || target.transformer_level !== stage.transformerLevel) {
            throw new Error(`${stage.label} transformer identity is invalid.`);
        }
        if (!Array.isArray(target.points) || target.points.length === 0) {
            throw new Error(`${stage.label} transformer has no profile points.`);
        }
        return {
            id,
            label: String(target.transformer_name || target.source_station_name || id),
            transformerLevel: target.transformer_level,
            datacompleetheid: target.datacompleetheid,
            points: target.points.map(normalizePoint),
            raw: target
        };
    }

    function normalizeStage(result, stageId) {
        const definition = STAGES[stageId];
        const stage = requireObject(
            result[definition.key],
            `Transformer result is missing the ${definition.label} stage.`
        );
        if (stage.complete !== true || !Array.isArray(stage.targets) || stage.targets.length === 0) {
            throw new Error(`${definition.label} transformer aggregation is incomplete.`);
        }
        return {
            id: stageId,
            label: definition.label,
            targets: stage.targets.map((target) => normalizeTarget(target, definition))
        };
    }

    function normalizeResponse(payload) {
        requireObject(payload, 'Transformer profile response must be an object.');
        if (payload.status !== 'completed') throw new Error('Transformer profile run did not complete.');
        const result = requireObject(payload.result, 'Transformer profile result is missing.');
        if (
            result.complete !== true ||
            result.persistence !== 'none' ||
            result.resolution !== 'PT15M'
        ) {
            throw new Error('Transformer profile result contract is incompatible.');
        }
        const datacompleetheid = Number(result.overall_datacompleetheid);
        if (!Number.isInteger(datacompleetheid) || datacompleetheid < 0 || datacompleetheid > 3) {
            throw new Error('Transformer profile datacompleetheid is invalid.');
        }
        return {
            sourceFeatureId: String(payload.feature?.source_feature_id || ''),
            profile: requireObject(payload.profile, 'Transformer source profile is missing.'),
            aggregationMode: String(result.aggregation_mode || ''),
            datacompleetheid,
            persistence: result.persistence,
            resolution: result.resolution,
            stages: {
                lv_mv: normalizeStage(result, 'lv_mv'),
                mv_hv: normalizeStage(result, 'mv_hv')
            },
            raw: payload
        };
    }

    function chartData(target) {
        requireObject(target, 'Select a transformer profile target.');
        if (!Array.isArray(target.points) || target.points.length === 0) {
            throw new Error('Selected transformer has no profile points.');
        }
        return {
            labels: target.points.map((point) => point.timestamp),
            demand: target.points.map((point) => point.demandPowerKw),
            production: target.points.map((point) => point.productionPowerKw),
            net: target.points.map((point) => point.netPowerKw)
        };
    }

    return Object.freeze({
        STAGES,
        SOURCES,
        normalizeSource,
        buildRequest,
        normalizeResponse,
        chartData
    });
}));
