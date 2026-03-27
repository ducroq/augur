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

function weatherFieldSeries(locData, field) {
    const entries = Object.entries(locData)
        .map(([ts, obj]) => {
            if (!obj || typeof obj !== 'object') return null;
            const val = resolveNumericValue(obj[field]);
            return val !== null ? { ts, val: addNoise(val) } : null;
        })
        .filter(Boolean)
        .sort((a, b) => new Date(a.ts) - new Date(b.ts));
    return { x: entries.map(d => d.ts), y: entries.map(d => d.val) };
}

export function processWeatherTemp(files, location) {
    const traces = [];
    const weather = files['weather_forecast_multi_location.json'];
    if (!weather || !weather.data || !weather.data[location]) return { traces, layout: {} };

    const locData = weather.data[location];

    // Temperature on left axis
    const tempXY = weatherFieldSeries(locData, 'temperature');
    if (tempXY.x.length > 0) traces.push(lineTrace('Temperature', tempXY.x, tempXY.y, COLORS.red, '°C'));

    // Wind speed on right axis
    const windXY = weatherFieldSeries(locData, 'wind_speed');
    if (windXY.x.length > 0) {
        const trace = lineTrace('Wind Speed', windXY.x, windXY.y, COLORS.blue, 'km/h');
        trace.yaxis = 'y2';
        traces.push(trace);
    }

    return {
        traces,
        layout: {
            yaxis: { title: 'Temperature (°C)' },
            yaxis2: { title: 'Wind Speed (km/h)', overlaying: 'y', side: 'right', gridcolor: 'rgba(0,0,0,0)' },
        },
    };
}

export function processWeatherCloud(files, location) {
    const traces = [];
    const weather = files['weather_forecast_multi_location.json'];
    if (!weather || !weather.data || !weather.data[location]) return { traces, layout: {} };

    const locData = weather.data[location];

    const fields = [
        { field: 'cloud_cover', label: 'Cloud Cover', color: COLORS.purple },
        { field: 'humidity', label: 'Humidity', color: COLORS.cyan },
    ];

    for (const cfg of fields) {
        const xy = weatherFieldSeries(locData, cfg.field);
        if (xy.x.length > 0) traces.push(lineTrace(cfg.label, xy.x, xy.y, cfg.color, '%'));
    }

    return { traces, layout: { yaxis: { title: 'Percentage (%)' } } };
}

// ── Grid Tab (3 separate charts) ────────────────────────────

export function processImbalance(files) {
    const traces = [];
    const imbalance = files['grid_imbalance.json'];
    if (!imbalance || !imbalance.data) return { traces, layout: {} };

    // Balance delta on left axis (MW)
    const deltaData = imbalance.data['balance_delta'];
    if (deltaData) {
        const xy = simpleTimeSeries(deltaData);
        if (xy.x.length > 0) traces.push(lineTrace('Balance Delta', xy.x, xy.y, COLORS.blue, 'MW'));
    }

    // Imbalance price on right axis (EUR/MWh)
    const priceData = imbalance.data['imbalance_price'];
    if (priceData) {
        const xy = simpleTimeSeries(priceData);
        if (xy.x.length > 0) {
            const trace = lineTrace('Imbalance Price', xy.x, xy.y, COLORS.red, 'EUR/MWh');
            trace.yaxis = 'y2';
            traces.push(trace);
        }
    }

    return {
        traces,
        layout: {
            yaxis: { title: 'Balance Delta (MW)' },
            yaxis2: { title: 'Imbalance Price (EUR/MWh)', overlaying: 'y', side: 'right', gridcolor: 'rgba(0,0,0,0)' },
        },
    };
}

export function processFlows(files) {
    const traces = [];
    const flows = files['cross_border_flows.json'];
    if (!flows || !flows.data || !flows.data.flows) return { traces, layout: {} };

    const flowData = flows.data.flows;
    const firstTs = Object.values(flowData)[0];
    if (!firstTs || typeof firstTs !== 'object') return { traces, layout: {} };

    const nlBorders = Object.keys(firstTs).filter(b => b.includes('NL'));
    const borderColors = [COLORS.cyan, COLORS.teal, COLORS.blue, COLORS.purple, COLORS.green, COLORS.amber, COLORS.pink, COLORS.orange, COLORS.red, COLORS.lime];
    nlBorders.forEach((border, i) => {
        const xy = fieldTimeSeries(flowData, border);
        if (xy.x.length > 0) {
            traces.push(lineTrace(border, xy.x, xy.y, borderColors[i % borderColors.length], 'MW'));
        }
    });

    return { traces, layout: { yaxis: { title: 'Flow (MW)' } } };
}

export function processLoad(files) {
    const traces = [];
    const load = files['load_forecast.json'];
    if (!load || !load.data || !load.data['NL']) return { traces, layout: {} };

    const nlData = load.data['NL'];
    const forecastXY = fieldTimeSeries(nlData, 'load_forecast');
    if (forecastXY.x.length > 0) traces.push(lineTrace('Forecast', forecastXY.x, forecastXY.y, COLORS.blue, 'MW'));

    const actualXY = fieldTimeSeries(nlData, 'load_actual');
    if (actualXY.x.length > 0) {
        const trace = lineTrace('Actual', actualXY.x, actualXY.y, COLORS.green, 'MW');
        trace.line = { width: 2, color: COLORS.green, dash: 'dot' };
        traces.push(trace);
    }

    return { traces, layout: { yaxis: { title: 'Load (MW)' } } };
}

// ── Grid Tab: NED Production ───────────────────────────────

/**
 * Process NED.nl renewable production data (solar, wind onshore, wind offshore).
 * Shows forecast vs actual as stacked area, converted from kW to MW.
 */
export function processNedProduction(files) {
    const traces = [];
    const ned = files['ned_production.json'];
    if (!ned || !ned.data) return { traces, layout: {} };

    const typeConfig = [
        { key: 'solar', label: 'Solar', color: COLORS.amber },
        { key: 'wind_onshore', label: 'Wind Onshore', color: COLORS.green },
        { key: 'wind_offshore', label: 'Wind Offshore', color: COLORS.cyan },
    ];

    // Actual production — stacked area
    for (const { key, label, color } of typeConfig) {
        const typeData = ned.data[key];
        if (!typeData || !typeData.actual) continue;

        const entries = Object.entries(typeData.actual)
            .filter(([, v]) => v && typeof v.volume_kwh === 'number')
            .map(([ts, v]) => ({ ts, val: addNoise(v.volume_kwh / 250) }))  // 15-min kWh → MW
            .sort((a, b) => new Date(a.ts) - new Date(b.ts));

        if (entries.length > 0) {
            traces.push({
                x: entries.map(d => d.ts),
                y: entries.map(d => d.val),
                type: 'scatter',
                mode: 'lines',
                name: `${label} (actual)`,
                line: { width: 0, color },
                fill: 'tonexty',
                fillcolor: color + '44',
                stackgroup: 'actual',
                hovertemplate: `<b>${label} Actual</b><br>%{x}<br>%{y:.0f} MW<extra></extra>`,
            });
        }
    }

    // Forecast total — dashed line overlay
    const forecastTotals = {};
    for (const { key } of typeConfig) {
        const typeData = ned.data[key];
        if (!typeData || !typeData.forecast) continue;

        for (const [ts, v] of Object.entries(typeData.forecast)) {
            if (v && typeof v.volume_kwh === 'number') {
                forecastTotals[ts] = (forecastTotals[ts] || 0) + v.volume_kwh / 250;
            }
        }
    }

    const forecastEntries = Object.entries(forecastTotals)
        .map(([ts, val]) => ({ ts, val: addNoise(val) }))
        .sort((a, b) => new Date(a.ts) - new Date(b.ts));

    if (forecastEntries.length > 0) {
        traces.push({
            x: forecastEntries.map(d => d.ts),
            y: forecastEntries.map(d => d.val),
            type: 'scatter',
            mode: 'lines',
            name: 'Total Forecast',
            line: { width: 2, color: '#ffffff', dash: 'dot' },
            hovertemplate: '<b>Total Forecast</b><br>%{x}<br>%{y:.0f} MW<extra></extra>',
        });
    }

    return { traces, layout: { yaxis: { title: 'Production (MW)' } } };
}

// ── Grid Tab: French Nuclear ────────────────────────────────

/**
 * Process ENTSO-E generation forecast — French nuclear actual + availability.
 * Dual axis: generation (GW, left) and availability (%, right).
 */
export function processNuclear(files) {
    const traces = [];
    const gen = files['generation_forecast.json'];
    if (!gen || !gen.data || !gen.data['FR']) return { traces, layout: {} };

    const frData = gen.data['FR'];

    const actualXY = fieldTimeSeries(frData, 'nuclear_actual');
    if (actualXY.x.length > 0) {
        traces.push({
            ...lineTrace('Generation', actualXY.x, actualXY.y.map(v => v / 1000), COLORS.cyan, 'GW'),
            fill: 'tozeroy',
            fillcolor: COLORS.cyan + '22',
        });
    }

    const availEntries = Object.entries(frData)
        .filter(([, obj]) => obj && typeof obj === 'object' && typeof obj.nuclear_availability === 'number')
        .map(([ts, obj]) => ({ ts, val: obj.nuclear_availability * 100 }))
        .sort((a, b) => new Date(a.ts) - new Date(b.ts));

    if (availEntries.length > 0) {
        traces.push({
            x: availEntries.map(d => d.ts),
            y: availEntries.map(d => d.val),
            type: 'scatter',
            mode: 'lines',
            name: 'Availability',
            line: { width: 2, color: COLORS.amber, dash: 'dot' },
            yaxis: 'y2',
            hovertemplate: '<b>Availability</b><br>%{x}<br>%{y:.1f}%<extra></extra>',
        });
    }

    return {
        traces,
        layout: {
            yaxis: { title: 'Generation (GW)' },
            yaxis2: { title: 'Availability (%)', overlaying: 'y', side: 'right', range: [0, 100], gridcolor: 'rgba(0,0,0,0)' },
        },
    };
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
