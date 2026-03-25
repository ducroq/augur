/**
 * Per-tab chart data processing and rendering.
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

function fieldTimeSeries(data, field) {
    const entries = Object.entries(data)
        .filter(([, obj]) => obj && typeof obj === 'object' && typeof obj[field] === 'number')
        .map(([ts, obj]) => ({ ts, val: addNoise(obj[field]) }))
        .sort((a, b) => new Date(a.ts) - new Date(b.ts));
    return { x: entries.map(d => d.ts), y: entries.map(d => d.val) };
}

function simpleTimeSeries(data) {
    const entries = Object.entries(data)
        .filter(([, v]) => typeof v === 'number')
        .map(([ts, v]) => ({ ts, val: addNoise(v) }))
        .sort((a, b) => new Date(a.ts) - new Date(b.ts));
    return { x: entries.map(d => d.ts), y: entries.map(d => d.val) };
}

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

// ── Forecast Tab: Wind ──────────────────────────────────────

/**
 * Get available wind locations.
 */
export function getWindLocations(files) {
    const wind = files['wind_forecast.json'];
    if (!wind || !wind['offshore_wind'] || !wind['offshore_wind'].data) return [];
    return Object.keys(wind['offshore_wind'].data);
}

/**
 * Process wind chart for a single location.
 */
export function processWind(files, location) {
    const traces = [];
    const wind = files['wind_forecast.json'];
    if (!wind) return { traces, layout: {} };

    const offshore = wind['offshore_wind'];
    if (offshore && offshore.data && offshore.data[location]) {
        const locData = offshore.data[location];
        const fields = [
            ['wind_speed_80m', 'Wind 80m', COLORS.blue],
            ['wind_speed_120m', 'Wind 120m', COLORS.cyan],
            ['wind_gusts_10m', 'Gusts 10m', COLORS.red],
        ];
        for (const [field, label, color] of fields) {
            const xy = fieldTimeSeries(locData, field);
            if (xy.x.length > 0) traces.push(lineTrace(label, xy.x, xy.y, color, 'm/s'));
        }
    }

    return { traces, layout: { yaxis: { title: 'Wind Speed (m/s)' } } };
}

// ── Forecast Tab: Solar ─────────────────────────────────────

export function getSolarLocations(files) {
    const solar = files['solar_forecast.json'];
    if (!solar || !solar.data) return [];
    return Object.keys(solar.data);
}

export function processSolar(files, location) {
    const traces = [];
    const solar = files['solar_forecast.json'];
    if (!solar || !solar.data || !solar.data[location]) return { traces, layout: {} };

    const locData = solar.data[location];
    const fields = [
        ['ghi', 'GHI (Global)', COLORS.amber],
        ['dni', 'DNI (Direct Normal)', COLORS.orange],
        ['dhi', 'DHI (Diffuse)', COLORS.lime],
    ];
    for (const [field, label, color] of fields) {
        const xy = fieldTimeSeries(locData, field);
        if (xy.x.length > 0) traces.push(lineTrace(label, xy.x, xy.y, color, 'W/m²'));
    }

    return { traces, layout: { yaxis: { title: 'Irradiance (W/m²)' } } };
}

// ── Forecast Tab: Weather ───────────────────────────────────

export function getWeatherLocations(files) {
    const weather = files['weather_forecast_multi_location.json'];
    if (!weather || !weather.data) return [];
    return Object.keys(weather.data);
}

export function processWeather(files, location) {
    const traces = [];
    const weather = files['weather_forecast_multi_location.json'];
    if (!weather || !weather.data || !weather.data[location]) return { traces, layout: {} };

    const locData = weather.data[location];
    const displayConfig = [
        { field: 'temperature', label: 'Temperature (°C)', color: COLORS.red },
        { field: 'wind_speed', label: 'Wind Speed (km/h)', color: COLORS.blue },
        { field: 'humidity', label: 'Humidity (%)', color: COLORS.cyan },
        { field: 'cloud_cover', label: 'Cloud Cover (%)', color: COLORS.purple },
    ];

    for (const cfg of displayConfig) {
        const entries = Object.entries(locData)
            .map(([ts, obj]) => {
                if (!obj || typeof obj !== 'object') return null;
                const val = resolveNumericValue(obj[cfg.field]);
                return val !== null ? { ts, val: addNoise(val) } : null;
            })
            .filter(Boolean)
            .sort((a, b) => new Date(a.ts) - new Date(b.ts));

        if (entries.length > 0) {
            traces.push(lineTrace(cfg.label, entries.map(d => d.ts), entries.map(d => d.val), cfg.color));
        }
    }

    return { traces, layout: { yaxis: { title: '°C / % / km/h' } } };
}

// ── Grid Tab (yesterday) ────────────────────────────────────

export function processGrid(files) {
    const traces = [];
    const colorCycle = [COLORS.red, COLORS.blue, COLORS.cyan, COLORS.purple, COLORS.green, COLORS.amber];
    let colorIdx = 0;

    // Grid imbalance
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

    // Cross-border flows
    const flows = files['cross_border_flows.json'];
    if (flows && flows.data && flows.data.flows) {
        const flowData = flows.data.flows;
        const firstTs = Object.values(flowData)[0];
        if (firstTs && typeof firstTs === 'object') {
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

    // Load forecast
    const load = files['load_forecast.json'];
    if (load && load.data) {
        const nlData = load.data['NL'];
        if (nlData) {
            const xy = fieldTimeSeries(nlData, 'load_forecast');
            if (xy.x.length > 0) traces.push(lineTrace('Load Forecast (NL)', xy.x, xy.y, COLORS.green, 'MW'));
        }
    }

    return { traces, layout: { yaxis: { title: 'MW / EUR' } } };
}

// ── Market Tab ──────────────────────────────────────────────

/**
 * Build market summary cards HTML.
 */
export function buildMarketCards(files) {
    const cards = [];

    // Market proxies: single-value snapshots
    const proxies = files['market_proxies.json'];
    if (proxies && proxies.data) {
        for (const [key, info] of Object.entries(proxies.data)) {
            if (typeof info !== 'object' || typeof info.price !== 'number') continue;
            cards.push({
                label: info.name || info.description || key,
                value: addNoise(info.price).toFixed(2),
                unit: info.units || 'USD',
                detail: info.date ? `As of ${info.date}` : '',
            });
        }
    }

    // Gas storage: latest fill level
    const storage = files['gas_storage.json'];
    if (storage && storage.data) {
        const records = Object.keys(storage.data)
            .sort((a, b) => Number(b) - Number(a))
            .map(k => storage.data[k])
            .filter(d => typeof d === 'object' && typeof d.fill_level_pct === 'number');

        if (records.length > 0) {
            const latest = records[0];
            cards.push({
                label: 'NL Gas Storage',
                value: addNoise(latest.fill_level_pct).toFixed(1) + '%',
                unit: 'fill level',
                detail: storage.metadata?.end_time
                    ? `As of ${storage.metadata.end_time.split('T')[0]}`
                    : '',
            });
            if (typeof latest.net_change_gwh === 'number') {
                const net = addNoise(latest.net_change_gwh);
                cards.push({
                    label: 'Storage Net Change',
                    value: (net > 0 ? '+' : '') + net.toFixed(0),
                    unit: 'GWh/day',
                    detail: net < 0 ? 'Net withdrawal' : 'Net injection',
                });
            }
        }
    }

    return cards;
}

/**
 * Process gas storage trend for small chart.
 */
export function processGasChart(files) {
    const traces = [];

    const storage = files['gas_storage.json'];
    if (storage && storage.data) {
        const records = Object.keys(storage.data)
            .sort((a, b) => Number(a) - Number(b))
            .map(k => storage.data[k])
            .filter(d => typeof d === 'object' && typeof d.fill_level_pct === 'number');

        if (records.length > 0) {
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
                hovertemplate: '<b>Fill Level</b><br>%{x}<br>%{y:.1f}%<extra></extra>',
            });
        }
    }

    return { traces, layout: { yaxis: { title: 'Fill Level (%)' } } };
}
