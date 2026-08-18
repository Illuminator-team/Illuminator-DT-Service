const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const profiles = require('../policy-tool-frontend/transformer-profiles.js');


function target(id, level, demand, production) {
    return {
        transformer_id: id,
        transformer_level: level,
        datacompleetheid: 1,
        points: demand.map((value, index) => ({
            timestamp: `2023-01-01T0${index}:00:00Z`,
            demand_power_kw: value,
            production_power_kw: production[index],
            net_power_kw: value + production[index]
        }))
    };
}


function response() {
    return {
        status: 'completed',
        feature: { source_feature_id: '1483AA' },
        profile: { profile_id: 'consumption-profile', resolution: 'PT15M' },
        result: {
            complete: true,
            persistence: 'none',
            resolution: 'PT15M',
            aggregation_mode: 'two_stage_provisional_estimated',
            overall_datacompleetheid: 1,
            source_to_lv_mv: {
                complete: true,
                targets: [target(
                    'grid-transformer-lv-mv-1',
                    'lv_mv_transformer',
                    [10, 12],
                    [0, 0]
                )]
            },
            lv_mv_to_mv_hv: {
                complete: true,
                targets: [target(
                    'grid-transformer-mv-hv-1',
                    'mv_hv_transformer',
                    [10, 12],
                    [0, 0]
                )]
            }
        }
    };
}


test('builds a one-day Consumption transformer request', () => {
    const request = profiles.buildRequest(
        { type: 'pc6', id: '1483 aa', label: '1483AA' },
        '2023-01-01'
    );
    assert.equal(request.url, '/policy-api/transformer-profiles/pc6/1483AA');
    assert.deepEqual(request.body, {
        start: '2023-01-01T00:00:00Z',
        end: '2023-01-02T00:00:00Z'
    });
});


test('builds a one-day PV transformer request on the 2024 calendar', () => {
    const request = profiles.buildRequest(
        { type: 'cbs_buurt', id: 'bu03610709', label: 'Landelijk gebied Noord' },
        '2024-06-01'
    );
    assert.equal(
        request.url,
        '/policy-api/transformer-profiles/pv/cbs-buurt/BU03610709'
    );
    assert.deepEqual(request.body, {
        start: '2024-06-01T00:00:00Z',
        end: '2024-06-02T00:00:00Z'
    });
});


test('rejects a profile date outside the model calendar', () => {
    assert.throws(
        () => profiles.buildRequest({ type: 'pc6', id: '1483AA' }, '2024-01-01'),
        /must be in 2023/
    );
});


test('normalizes both transformer stages and chart values', () => {
    const result = profiles.normalizeResponse(response());
    assert.equal(result.stages.lv_mv.targets[0].id, 'grid-transformer-lv-mv-1');
    assert.equal(result.stages.mv_hv.targets[0].id, 'grid-transformer-mv-hv-1');
    assert.deepEqual(profiles.chartData(result.stages.lv_mv.targets[0]), {
        labels: ['2023-01-01T00:00:00Z', '2023-01-01T01:00:00Z'],
        demand: [10, 12],
        production: [0, 0],
        net: [10, 12]
    });
});


test('rejects an inconsistent canonical net-power value', () => {
    const payload = response();
    payload.result.source_to_lv_mv.targets[0].points[0].net_power_kw = 999;
    assert.throws(
        () => profiles.normalizeResponse(payload),
        /canonical net-power sum/
    );
});


test('rejects a response that drifts from the canonical timestamp field', () => {
    const payload = response();
    const point = payload.result.source_to_lv_mv.targets[0].points[0];
    point.interval_start_utc = point.timestamp;
    delete point.timestamp;
    assert.throws(
        () => profiles.normalizeResponse(payload),
        /invalid timestamp/
    );
});


test('rejects missing transformer stages', () => {
    const payload = response();
    delete payload.result.lv_mv_to_mv_hv;
    assert.throws(
        () => profiles.normalizeResponse(payload),
        /missing the MV\/HV stage/
    );
});


test('dashboard exposes transformer level, target, date and calculation controls', () => {
    const frontend = path.join(__dirname, '..', 'policy-tool-frontend');
    const html = fs.readFileSync(path.join(frontend, 'index.html'), 'utf8');
    const script = fs.readFileSync(path.join(frontend, 'script.js'), 'utf8');
    const scenarioPanel = html.match(/<section id="scenario-panel"[\s\S]*?<\/section>/)?.[0];

    assert.ok(scenarioPanel, 'scenario panel is present');
    assert.match(scenarioPanel, /id="transformer-profile-date"/);
    assert.match(scenarioPanel, /id="load-transformer-profiles-btn"/);
    assert.match(scenarioPanel, /data-profile-stage="lv_mv"/);
    assert.match(scenarioPanel, /data-profile-stage="mv_hv"/);
    assert.match(scenarioPanel, /id="transformer-profile-select"/);
    assert.match(scenarioPanel, /id="transformer-profile-canvas"/);
    assert.ok(
        html.indexOf('transformer-profiles.js') < html.indexOf('script.js'),
        'profile adapter loads before dashboard behavior'
    );
    assert.match(script, /function loadTransformerProfiles\(\)/);
    assert.match(script, /function renderTransformerProfileChart\(target\)/);
    assert.match(script, /type: 'pc6'/);
    assert.match(script, /type: 'cbs_buurt'/);
    assert.match(script, /demand_power_kw|data\.demand/);
    assert.match(script, /data\.production/);
    assert.match(script, /data\.net/);
});


test('legacy scenario controls remain available beside transformer profiles', () => {
    const html = fs.readFileSync(
        path.join(__dirname, '..', 'policy-tool-frontend', 'index.html'),
        'utf8'
    );
    assert.equal((html.match(/id="run-sim-btn"/g) || []).length, 1);
    assert.equal((html.match(/id="load-transformer-profiles-btn"/g) || []).length, 1);
    assert.match(html, /id="input-gas"/);
    assert.match(html, /id="input-pv"/);
    assert.match(html, /id="simulation-output"/);
    assert.match(html, /id="transformer-profile-output"/);
});
