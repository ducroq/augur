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
 * Extract time series from { timestamp: { field: value } } for a specific field.
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

/**
 * Resolve a nested weather value to a number.
 * Handles: plain number, { degrees: N }, { distance: N }, { percent: N }, { meanSeaLevelMillibars: N }
 */
function resolveNumericValue(val) {
    if (typeof val === 'number') return val;
    if (val && typeof val === 'object') {
        if (typeof val.degrees === 'number') return val.degrees;
        if (typeof val.distance === 'number') return val.distance;
        if (typeof val.percent === 'number') return val.percent;
        if (typeof val.meanSeaLevelMillibars === 'number') return val.meanSeaLevelMillibars;
    }
    return null;
}

// ── Renewables ──────────────────────────────────────────────

export function processRenewables(files) {
    const traces = [];

    // Wind: show NL wind_total from entsoe_wind_generation dataset
    const wind = files['wind_forecast.json'];
    if (wind) {
        for (const [dsKey, dsVal] of Object.entries(wind)) {
            if (dsKey === 'version' || typeof dsVal !== 'object' || !dsVal.data) continue;
            const nlData = dsVal.data['NL'];
            if (!nlData) continue;

            const firstVal = Object.values(nlData)[0];
            if (typeof firstVal === 'object' && firstVal !== null) {
                const field = 'wind_total' in firstVal ? 'wind_total' :
                    Object.keys(firstVal).find(k => typeof firstVal[k] === 'number');
                if (field) {
                    const xy = fieldTimeSeries(nlData, field);
                    if (xy.x.length > 0) {
                        const label = dsKey.includes('offshore') ? 'Offshore Wind' : 'Wind Total (NL)';
                        traces.push(lineTrace(label, xy.x, xy.y, dsKey.includes('offshore') ? COLORS.cyan : COLORS.blue, 'MW'));
                    }
                }
            }
        }
    }

    // Solar: { metadata, data: { location: { ts: { ghi, direct, ... } } } }
    const solar = files['solar_forecast.json'];
    if (solar && solar.data) {
        const nlLoc = Object.keys(solar.data).find(k => k.includes('NL')) || Object.keys(solar.data)[0];
        if (nlLoc) {
            const locData = solar.data[nlLoc];
            // Show GHI (global horizontal irradiance) as the primary solar metric
            const xy = fieldTimeSeries(locData, 'ghi');
            if (xy.x.length > 0) {
                traces.push(lineTrace(`Solar GHI (${nlLoc})`, xy.x, xy.y, COLORS.amber, 'W/m²'));
            }
        }
    }

    // Generation forecast
    const gen = files['generation_forecast.json'];
    if (gen && gen.data) {
        const data = gen.data;
        const firstKey = Object.keys(data)[0];
        if (firstKey) {
            const firstVal = data[firstKey];
            const isTimestamp = /^\d{4}-\d{2}/.test(firstKey);
            if (isTimestamp && typeof firstVal === 'object') {
                const field = Object.keys(firstVal).find(k => typeof firstVal[k] === 'number');
                if (field) {
                    const xy = fieldTimeSeries(data, field);
                    if (xy.x.length > 0) traces.push(lineTrace('Generation', xy.x, xy.y, COLORS.green, 'MW'));
                }
            } else if (!isTimestamp && typeof firstVal === 'object') {
                // Nested by country
                const nlData = data['NL'] || data[firstKey];
                if (nlData) {
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
    }

    return { traces, layout: { yaxis: { title: 'MW / W/m²' } } };
}

// ── Grid ────────────────────────────────────────────────────

export function processGrid(files) {
    const traces = [];

    // Grid imbalance: { data: { imbalance_price: { ts: val }, balance_delta: { ts: val }, direction: { ts: str } } }
    const imbalance = files['grid_imbalance.json'];
    if (imbalance && imbalance.data) {
        const seriesConfig = {
            'imbalance_price': { color: COLORS.red, unit: 'EUR/MWh' },
            'balance_delta': { color: COLORS.blue, unit: 'MW' },
        };
        for (const [series, cfg] of Object.entries(seriesConfig)) {
            const tsData = imbalance.data[series];
            if (!tsData) continue;
            const xy = simpleTimeSeries(tsData);
            if (xy.x.length > 0) {
                traces.push(lineTrace(series.replace(/_/g, ' '), xy.x, xy.y, cfg.color, cfg.unit));
            }
        }
    }

    // Cross-border flows: { data: { flows: { ts: { "NL→DE": val } } } }
    const flows = files['cross_border_flows.json'];
    if (flows && flows.data && flows.data.flows) {
        const flowData = flows.data.flows;
        const firstTs = Object.values(flowData)[0];
        if (firstTs && typeof firstTs === 'object') {
            // Show NL import/export borders
            const nlBorders = Object.keys(firstTs).filter(b => b.includes('NL')).slice(0, 4);
            const borderColors = [COLORS.cyan, COLORS.teal, COLORS.purple, COLORS.pink];
            nlBorders.forEach((border, i) => {
                const xy = fieldTimeSeries(flowData, border);
                if (xy.x.length > 0) {
                    traces.push(lineTrace(border, xy.x, xy.y, borderColors[i % borderColors.length], 'MW'));
                }
            });
        }
    }

    // Load forecast: { data: { NL: { ts: { load_forecast: val } } } }
    const load = files['load_forecast.json'];
    if (load && load.data) {
        const nlData = load.data['NL'];
        if (nlData) {
            const xy = fieldTimeSeries(nlData, 'load_forecast');
            if (xy.x.length > 0) {
                traces.push(lineTrace('Load Forecast (NL)', xy.x, xy.y, COLORS.green, 'MW'));
            }
        }
    }

    return { traces, layout: { yaxis: { title: 'MW / EUR' } } };
}

// ── Weather ─────────────────────────────────────────────────
// { metadata, data: { location: { ts: { temperature: {degrees: N}, humidity: N, ... } } } }

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

    // Weather fields we want to display, in priority order
    const displayConfig = [
        { field: 'temperature', label: 'Temperature (°C)', color: COLORS.red },
        { field: 'wind_speed', label: 'Wind Speed (km/h)', color: COLORS.blue },
        { field: 'humidity', label: 'Humidity (%)', color: COLORS.cyan },
        { field: 'cloud_cover', label: 'Cloud Cover (%)', color: COLORS.purple },
        { field: 'uv_index', label: 'UV Index', color: COLORS.amber },
    ];

    for (const cfg of displayConfig) {
        const entries = Object.entries(locData)
            .map(([ts, obj]) => {
                if (!obj || typeof obj !== 'object') return null;
                const raw = obj[cfg.field];
                const val = resolveNumericValue(raw);
                return val !== null ? { ts, val: addNoise(val) } : null;
            })
            .filter(Boolean)
            .sort((a, b) => new Date(a.ts) - new Date(b.ts));

        if (entries.length > 0) {
            traces.push(lineTrace(
                cfg.label,
                entries.map(d => d.ts),
                entries.map(d => d.val),
                cfg.color,
            ));
        }
    }

    return {
        traces,
        layout: { yaxis: { title: 'Value' } },
        locations,
        selectedLocation: location,
    };
}

// ── Gas & Storage ───────────────────────────────────────────
// gas_storage.json: { metadata: { start_time, end_time }, data: { "0": { fill_level_pct, ... } } }
// gas_flows.json: { metadata, data: { ts: { entry_total_gwh, ... } } }

export function processGas(files) {
    const traces = [];

    // Gas storage: indexed daily records — derive dates from metadata
    const storage = files['gas_storage.json'];
    if (storage && storage.data) {
        const records = Object.keys(storage.data)
            .sort((a, b) => Number(a) - Number(b))
            .map(k => storage.data[k])
            .filter(d => typeof d === 'object' && typeof d.fill_level_pct === 'number');

        if (records.length > 0) {
            // Generate dates from metadata start_time
            const startDate = new Date(storage.metadata?.start_time || Date.now());
            const x = records.map((_, i) => {
                const d = new Date(startDate);
                d.setDate(d.getDate() + i);
                return d.toISOString().split('T')[0];
            });
            const y = records.map(d => addNoise(d.fill_level_pct));
            traces.push({
                x, y,
                type: 'scatter',
                mode: 'lines+markers',
                name: 'Storage Fill Level',
                line: { width: 2, color: COLORS.orange },
                marker: { size: 6, color: COLORS.orange },
                hovertemplate: '<b>Storage Fill Level</b><br>%{x}<br>%{y:.1f}%<extra></extra>',
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
            const fieldConfig = [
                ['net_flow_gwh', 'Net Flow', COLORS.teal],
                ['entry_total_gwh', 'Entry', COLORS.green],
                ['exit_total_gwh', 'Exit', COLORS.red],
            ];
            for (const [field, label, color] of fieldConfig) {
                if (typeof firstVal[field] === 'number') {
                    const xy = fieldTimeSeries(flowsFile.data, field);
                    if (xy.x.length > 0) {
                        traces.push(lineTrace(label, xy.x, xy.y, color, 'GWh'));
                    }
                }
            }
        }
    }

    return { traces, layout: { yaxis: { title: 'GWh / %' } } };
}
