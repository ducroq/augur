/**
 * Per-tab chart data processing and rendering.
 * Each function takes raw data files and returns Plotly traces.
 * @module tab-charts
 */

import { addNoise } from './noise.js';

const COLORS = {
    blue: '#60a5fa',
    green: '#10b981',
    amber: '#f59e0b',
    red: '#ef4444',
    purple: '#a78bfa',
    cyan: '#22d3ee',
    pink: '#f472b6',
    lime: '#84cc16',
    orange: '#fb923c',
    teal: '#2dd4bf',
};

/**
 * Create a standard line trace.
 */
function lineTrace(name, x, y, color, unit = '') {
    return {
        x, y,
        type: 'scatter',
        mode: 'lines',
        name,
        line: { width: 2, color },
        hovertemplate: `<b>${name}</b><br>%{x}<br>%{y:.2f} ${unit}<extra></extra>`,
    };
}

/**
 * Extract time series from a nested object: { timestamp: { field: value } }
 * Returns sorted { x, y } for a specific field.
 */
function fieldTimeSeries(data, field) {
    const entries = Object.entries(data)
        .filter(([, obj]) => obj && typeof obj === 'object' && typeof obj[field] === 'number')
        .map(([ts, obj]) => ({ ts, val: addNoise(obj[field]) }))
        .sort((a, b) => new Date(a.ts) - new Date(b.ts));
    return { x: entries.map(d => d.ts), y: entries.map(d => d.val) };
}

/**
 * Extract time series from { timestamp: number }
 */
function simpleTimeSeries(data) {
    const entries = Object.entries(data)
        .filter(([, v]) => typeof v === 'number')
        .map(([ts, v]) => ({ ts, val: addNoise(v) }))
        .sort((a, b) => new Date(a.ts) - new Date(b.ts));
    return { x: entries.map(d => d.ts), y: entries.map(d => d.val) };
}

// ── Renewables ──────────────────────────────────────────────
// wind_forecast.json: { version, entsoe_wind_generation: { metadata, data: { NL: { ts: {wind_total, ...} }, ... } }, offshore_wind: ... }
// solar_forecast.json: { metadata, data: { location: { ts: {fields} } } }
// generation_forecast.json: { metadata, data: ... }

export function processRenewables(files) {
    const traces = [];

    // Wind: show NL wind_total from entsoe_wind_generation
    const wind = files['wind_forecast.json'];
    if (wind) {
        // Schema v2.0: datasets under named keys
        for (const [dsKey, dsVal] of Object.entries(wind)) {
            if (dsKey === 'version' || typeof dsVal !== 'object' || !dsVal.data) continue;
            const nlData = dsVal.data['NL'] || dsVal.data[Object.keys(dsVal.data)[0]];
            if (!nlData) continue;

            const firstVal = Object.values(nlData)[0];
            if (typeof firstVal === 'object' && firstVal !== null) {
                // Pick wind_total if available, otherwise first numeric field
                const field = 'wind_total' in firstVal ? 'wind_total' :
                    Object.keys(firstVal).find(k => typeof firstVal[k] === 'number');
                if (field) {
                    const xy = fieldTimeSeries(nlData, field);
                    if (xy.x.length > 0) {
                        const label = dsKey.replace(/_/g, ' ').replace(/entsoe /i, '');
                        traces.push(lineTrace(label, xy.x, xy.y, COLORS.blue, 'MW'));
                    }
                }
            }
        }
    }

    // Solar: { metadata, data: { location: { ts: {fields} } } }
    const solar = files['solar_forecast.json'];
    if (solar && solar.data) {
        // Pick a NL location
        const locKey = Object.keys(solar.data).find(k => k.includes('NL')) || Object.keys(solar.data)[0];
        if (locKey) {
            const locData = solar.data[locKey];
            const firstVal = Object.values(locData)[0];
            if (typeof firstVal === 'object' && firstVal !== null) {
                const field = 'solar_irradiance' in firstVal ? 'solar_irradiance' :
                    Object.keys(firstVal).find(k => typeof firstVal[k] === 'number');
                if (field) {
                    const xy = fieldTimeSeries(locData, field);
                    if (xy.x.length > 0) {
                        traces.push(lineTrace(`Solar (${locKey})`, xy.x, xy.y, COLORS.amber, 'W/m²'));
                    }
                }
            }
        }
    }

    // Generation forecast
    const gen = files['generation_forecast.json'];
    if (gen && gen.data) {
        const dataSection = gen.data;
        // Could be { country: { ts: {fields} } } or { ts: value }
        const firstKey = Object.keys(dataSection)[0];
        const firstVal = dataSection[firstKey];
        if (typeof firstVal === 'object' && !Array.isArray(firstVal)) {
            // Nested by country or by timestamp
            const isTimestamp = /^\d{4}-\d{2}/.test(firstKey);
            if (isTimestamp) {
                // { ts: { fields } }
                const field = Object.keys(firstVal).find(k => typeof firstVal[k] === 'number');
                if (field) {
                    const xy = fieldTimeSeries(dataSection, field);
                    if (xy.x.length > 0) traces.push(lineTrace('Generation', xy.x, xy.y, COLORS.green, 'MW'));
                }
            } else {
                // { country: { ts: ... } }
                const nlData = dataSection['NL'] || dataSection[firstKey];
                const innerFirst = Object.values(nlData)[0];
                if (typeof innerFirst === 'number') {
                    const xy = simpleTimeSeries(nlData);
                    if (xy.x.length > 0) traces.push(lineTrace('Generation (NL)', xy.x, xy.y, COLORS.green, 'MW'));
                } else if (typeof innerFirst === 'object') {
                    const field = Object.keys(innerFirst).find(k => typeof innerFirst[k] === 'number');
                    if (field) {
                        const xy = fieldTimeSeries(nlData, field);
                        if (xy.x.length > 0) traces.push(lineTrace('Generation (NL)', xy.x, xy.y, COLORS.green, 'MW'));
                    }
                }
            }
        }
    }

    return { traces, layout: { yaxis: { title: 'MW' } } };
}

// ── Grid ────────────────────────────────────────────────────
// grid_imbalance.json: { metadata, data: { imbalance_price: { ts: val }, balance_delta: { ts: val } } }
// cross_border_flows.json: { metadata, data: { flows: { ts: { border: val } }, summary: ... } }
// load_forecast.json: { metadata, data: { NL: { ts: { load_forecast: val, ... } }, ... } }

export function processGrid(files) {
    const traces = [];
    const colorCycle = [COLORS.red, COLORS.blue, COLORS.cyan, COLORS.purple, COLORS.green, COLORS.amber];
    let colorIdx = 0;

    // Grid imbalance: { data: { series_name: { ts: value } } }
    const imbalance = files['grid_imbalance.json'];
    if (imbalance && imbalance.data) {
        for (const [series, tsData] of Object.entries(imbalance.data)) {
            if (typeof tsData !== 'object') continue;
            const firstVal = Object.values(tsData)[0];
            if (typeof firstVal === 'number') {
                const xy = simpleTimeSeries(tsData);
                if (xy.x.length > 0) {
                    traces.push(lineTrace(series.replace(/_/g, ' '), xy.x, xy.y, colorCycle[colorIdx++ % colorCycle.length], imbalance.metadata?.units || ''));
                }
            }
        }
    }

    // Cross-border flows: { data: { flows: { ts: { border: val } } } }
    const flows = files['cross_border_flows.json'];
    if (flows && flows.data && flows.data.flows) {
        const flowData = flows.data.flows;
        const firstTs = Object.values(flowData)[0];
        if (firstTs && typeof firstTs === 'object') {
            // Show top NL borders
            const borders = Object.keys(firstTs).filter(b => b.includes('NL'));
            borders.slice(0, 4).forEach(border => {
                const xy = fieldTimeSeries(flowData, border);
                if (xy.x.length > 0) {
                    traces.push(lineTrace(border, xy.x, xy.y, colorCycle[colorIdx++ % colorCycle.length], 'MW'));
                }
            });
        }
    }

    // Load forecast: { data: { NL: { ts: { load_forecast: val } } } }
    const load = files['load_forecast.json'];
    if (load && load.data) {
        const nlData = load.data['NL'] || load.data[Object.keys(load.data)[0]];
        if (nlData) {
            const firstVal = Object.values(nlData)[0];
            if (typeof firstVal === 'object') {
                const field = 'load_forecast' in firstVal ? 'load_forecast' :
                    Object.keys(firstVal).find(k => typeof firstVal[k] === 'number');
                if (field) {
                    const xy = fieldTimeSeries(nlData, field);
                    if (xy.x.length > 0) traces.push(lineTrace('Load Forecast (NL)', xy.x, xy.y, COLORS.purple, 'MW'));
                }
            }
        }
    }

    return { traces, layout: { yaxis: { title: 'MW / EUR' } } };
}

// ── Weather ─────────────────────────────────────────────────
// { metadata, data: { location: { ts: { temp, wind, etc } } } }

export function processWeather(files, selectedLocation = null) {
    const traces = [];
    const fileData = files['weather_forecast_multi_location.json'];
    if (!fileData || !fileData.data) return { traces, layout: {}, locations: [] };

    const locations = Object.keys(fileData.data);
    const location = selectedLocation
        || locations.find(l => l.toLowerCase().includes('bilt'))
        || locations.find(l => l.includes('NL'))
        || locations[0];

    const locData = fileData.data[location];
    if (!locData) return { traces, layout: {}, locations, selectedLocation: location };

    const firstVal = Object.values(locData)[0];
    if (typeof firstVal === 'object' && firstVal !== null) {
        const fields = Object.keys(firstVal).filter(k => typeof firstVal[k] === 'number');
        const fieldColors = [COLORS.red, COLORS.blue, COLORS.amber, COLORS.green, COLORS.purple, COLORS.cyan];

        // Show key weather fields (limit to avoid clutter)
        const priorityFields = ['temperature_2m', 'wind_speed_10m', 'solar_irradiance', 'cloud_cover',
            'temperature', 'wind_speed', 'humidity', 'pressure'];
        const displayFields = fields.filter(f => priorityFields.some(p => f.includes(p))).slice(0, 5)
            || fields.slice(0, 5);

        (displayFields.length > 0 ? displayFields : fields.slice(0, 5)).forEach((field, i) => {
            const xy = fieldTimeSeries(locData, field);
            if (xy.x.length > 0) {
                traces.push(lineTrace(
                    field.replace(/_/g, ' '),
                    xy.x, xy.y,
                    fieldColors[i % fieldColors.length],
                ));
            }
        });
    }

    return {
        traces,
        layout: { yaxis: { title: 'Value' } },
        locations,
        selectedLocation: location,
    };
}

// ── Gas & Storage ───────────────────────────────────────────
// gas_storage.json: { metadata, data: { "0": { fill_level_pct, ... }, "1": {...} } } — indexed records
// gas_flows.json: { metadata, data: { ts: { entry_total_gwh, exit_total_gwh, ... } } }

export function processGas(files) {
    const traces = [];

    // Gas storage: indexed records, pick fill_level_pct
    const storage = files['gas_storage.json'];
    if (storage && storage.data) {
        const entries = Object.values(storage.data)
            .filter(d => typeof d === 'object' && typeof d.fill_level_pct === 'number');
        if (entries.length > 0) {
            // These are daily records but have no timestamp key — use index as x
            const x = entries.map((_, i) => `Day ${i + 1}`);
            const y = entries.map(d => addNoise(d.fill_level_pct));
            traces.push({
                x, y,
                type: 'bar',
                name: 'Fill Level (%)',
                marker: { color: COLORS.orange },
                hovertemplate: '<b>Fill Level</b><br>%{x}<br>%{y:.1f}%<extra></extra>',
            });
        }
    }

    // Gas flows: { ts: { entry_total_gwh, exit_total_gwh, net_flow_gwh } }
    const flowsFile = files['gas_flows.json'];
    if (flowsFile && flowsFile.data) {
        const firstKey = Object.keys(flowsFile.data)[0];
        const firstVal = flowsFile.data[firstKey];
        const isTimestamp = /^\d{4}-\d{2}/.test(firstKey);

        if (isTimestamp && typeof firstVal === 'object') {
            for (const [field, color] of [['net_flow_gwh', COLORS.teal], ['entry_total_gwh', COLORS.green], ['exit_total_gwh', COLORS.red]]) {
                if (typeof firstVal[field] === 'number') {
                    const xy = fieldTimeSeries(flowsFile.data, field);
                    if (xy.x.length > 0) {
                        traces.push(lineTrace(field.replace(/_/g, ' '), xy.x, xy.y, color, 'GWh'));
                    }
                }
            }
        }
    }

    return { traces, layout: { yaxis: { title: 'GWh / %' } } };
}
