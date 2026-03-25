/**
 * Per-tab chart data processing and rendering.
 * Each function takes raw data files and returns Plotly traces.
 * @module tab-charts
 */

import { addNoise } from './noise.js';

// Color palette for consistent styling across tabs
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
 * Extract datasets from a data file (schema v2.1).
 * Returns array of { key, metadata, data } for each dataset in the file.
 */
function extractDatasets(fileData) {
    if (!fileData || typeof fileData !== 'object') return [];
    const datasets = [];
    for (const [key, value] of Object.entries(fileData)) {
        if (key === 'version') continue;
        if (value && typeof value === 'object' && value.data) {
            datasets.push({ key, metadata: value.metadata || {}, data: value.data });
        }
    }
    return datasets;
}

/**
 * Convert a dataset's data object into sorted x/y arrays with noise.
 */
function datasetToXY(data) {
    const entries = Object.entries(data)
        .map(([ts, val]) => ({ ts, val: typeof val === 'number' ? addNoise(val) : val }))
        .filter(d => typeof d.val === 'number')
        .sort((a, b) => new Date(a.ts) - new Date(b.ts));
    return {
        x: entries.map(d => d.ts),
        y: entries.map(d => d.val),
    };
}

/**
 * Create a standard line trace.
 */
function lineTrace(name, xy, color, opts = {}) {
    return {
        x: xy.x,
        y: xy.y,
        type: 'scatter',
        mode: 'lines',
        name,
        line: { width: 2, color, ...opts.line },
        hovertemplate: `<b>${name}</b><br>%{x}<br>%{y:.2f} ${opts.unit || ''}<extra></extra>`,
        ...opts.extra,
    };
}

// ── Renewables ──────────────────────────────────────────────

export function processRenewables(files) {
    const traces = [];
    const colorMap = {
        wind: COLORS.blue,
        solar: COLORS.amber,
        generation: COLORS.green,
    };
    const fileMap = {
        'wind_forecast.json': { label: 'Wind', color: colorMap.wind },
        'solar_forecast.json': { label: 'Solar', color: colorMap.solar },
        'generation_forecast.json': { label: 'Generation', color: colorMap.generation },
    };

    for (const [filename, cfg] of Object.entries(fileMap)) {
        const fileData = files[filename];
        if (!fileData) continue;
        const datasets = extractDatasets(fileData);
        datasets.forEach((ds, i) => {
            const xy = datasetToXY(ds.data);
            if (xy.x.length === 0) return;
            const unit = ds.metadata.units || 'MW';
            const name = datasets.length > 1 ? `${cfg.label} (${ds.key})` : cfg.label;
            traces.push(lineTrace(name, xy, cfg.color, { unit, line: { width: i === 0 ? 2 : 1 } }));
        });
    }

    return {
        traces,
        layout: {
            yaxis: { title: 'Generation (MW)' },
        },
    };
}

// ── Grid ────────────────────────────────────────────────────

export function processGrid(files) {
    const traces = [];
    const configs = [
        { file: 'grid_imbalance.json', label: 'Imbalance', color: COLORS.red },
        { file: 'cross_border_flows.json', label: 'Cross-border', color: COLORS.cyan },
        { file: 'load_forecast.json', label: 'Load', color: COLORS.purple },
    ];

    for (const cfg of configs) {
        const fileData = files[cfg.file];
        if (!fileData) continue;
        const datasets = extractDatasets(fileData);
        datasets.forEach(ds => {
            const xy = datasetToXY(ds.data);
            if (xy.x.length === 0) return;
            const unit = ds.metadata.units || 'MW';
            const name = datasets.length > 1 ? `${cfg.label} (${ds.key})` : cfg.label;
            traces.push(lineTrace(name, xy, cfg.color, { unit }));
        });
    }

    return {
        traces,
        layout: {
            yaxis: { title: 'MW' },
        },
    };
}

// ── Weather ─────────────────────────────────────────────────

export function processWeather(files, selectedLocation = null) {
    const traces = [];
    const fileData = files['weather_forecast_multi_location.json'];
    if (!fileData) return { traces, layout: {}, locations: [] };

    const datasets = extractDatasets(fileData);
    const locations = datasets.map(ds => ds.key);

    // Pick a default location (De Bilt is the Dutch reference station)
    const location = selectedLocation || locations.find(l => l.toLowerCase().includes('bilt')) || locations[0];
    const ds = datasets.find(d => d.key === location);

    if (ds) {
        // Weather data may have nested objects per timestamp (temp, wind, etc.)
        // or simple numeric values. Handle both.
        const firstValue = Object.values(ds.data)[0];

        if (typeof firstValue === 'object' && firstValue !== null) {
            // Nested: { timestamp: { temperature: X, wind_speed: Y, ... } }
            const fields = Object.keys(firstValue).filter(k => typeof firstValue[k] === 'number');
            const fieldColors = [COLORS.red, COLORS.blue, COLORS.amber, COLORS.green, COLORS.purple];

            fields.forEach((field, i) => {
                const entries = Object.entries(ds.data)
                    .map(([ts, obj]) => ({ ts, val: typeof obj[field] === 'number' ? addNoise(obj[field]) : null }))
                    .filter(d => d.val !== null)
                    .sort((a, b) => new Date(a.ts) - new Date(b.ts));

                if (entries.length > 0) {
                    traces.push(lineTrace(
                        field.replace(/_/g, ' '),
                        { x: entries.map(d => d.ts), y: entries.map(d => d.val) },
                        fieldColors[i % fieldColors.length],
                        { unit: '' }
                    ));
                }
            });
        } else {
            // Simple numeric: { timestamp: value }
            const xy = datasetToXY(ds.data);
            if (xy.x.length > 0) {
                traces.push(lineTrace(location, xy, COLORS.red, { unit: ds.metadata.units || '' }));
            }
        }
    }

    return {
        traces,
        layout: {
            yaxis: { title: ds?.metadata?.units || 'Value' },
        },
        locations,
        selectedLocation: location,
    };
}

// ── Gas & Storage ───────────────────────────────────────────

export function processGas(files) {
    const traces = [];
    const configs = [
        { file: 'gas_storage.json', label: 'Gas Storage', color: COLORS.orange },
        { file: 'gas_flows.json', label: 'Gas Flows', color: COLORS.teal },
    ];

    for (const cfg of configs) {
        const fileData = files[cfg.file];
        if (!fileData) continue;
        const datasets = extractDatasets(fileData);
        datasets.forEach(ds => {
            const xy = datasetToXY(ds.data);
            if (xy.x.length === 0) return;
            const unit = ds.metadata.units || '';
            const name = datasets.length > 1 ? `${cfg.label} (${ds.key})` : cfg.label;
            traces.push(lineTrace(name, xy, cfg.color, { unit }));
        });
    }

    return {
        traces,
        layout: {
            yaxis: { title: 'Volume' },
        },
    };
}
