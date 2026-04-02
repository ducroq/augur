/**
 * Model explanation visualizations for the Model tab.
 * Static charts use pre-computed data from model-viz-data.js.
 * Performance charts use live data from augur_forecast.json.
 * @module model-viz
 */

import {
    CORRELATION, FEATURE_IMPORTANCE_BY_HORIZON, HOURLY_PROFILE,
    WIND_VS_PRICE,
} from './model-viz-data.js';

const DARK = {
    paper: '#111111',
    plot: '#111111',
    grid: '#333333',
    text: '#cccccc',
    font: '-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif',
};

function darkLayout(overrides = {}) {
    return {
        paper_bgcolor: DARK.paper,
        plot_bgcolor: DARK.plot,
        font: { color: DARK.text, family: DARK.font, size: 12 },
        margin: { l: 60, r: 30, t: 40, b: 50 },
        ...overrides,
    };
}

const plotConfig = { responsive: true, displayModeBar: false };

// ── 1. Feature Importance by Horizon (grouped bar) ──────────

export function renderFeatureImportance(elementId) {
    const { horizons, r2, features, values } = FEATURE_IMPORTANCE_BY_HORIZON;

    const colors = {
        '1h': '#60a5fa',
        '6h': '#10b981',
        '24h': '#f59e0b',
        '48h': '#ef4444',
    };

    const traces = horizons.map(h => ({
        type: 'bar',
        orientation: 'h',
        name: `${h} ahead (R²=${r2[horizons.indexOf(h)].toFixed(2)})`,
        y: features,
        x: values[h],
        marker: { color: colors[h], opacity: 0.85 },
        hovertemplate: `<b>%{y}</b><br>${h}: %{x:.1f}<extra></extra>`,
    }));

    Plotly.newPlot(elementId, traces, darkLayout({
        barmode: 'group',
        xaxis: { title: 'Lasso |coefficient|', gridcolor: DARK.grid },
        yaxis: { autorange: 'reversed', gridcolor: DARK.grid, tickfont: { size: 10 } },
        legend: { orientation: 'h', y: 1.08, xanchor: 'center', x: 0.5, font: { size: 10 } },
        margin: { l: 140, r: 30, t: 40, b: 40 },
    }), plotConfig);
}

// ── 2. Correlation Heatmap ──────────────────────────────────

export function renderCorrelation(elementId) {
    const labels = CORRELATION.columns.map(c => c.replace(/_/g, ' '));
    const text = CORRELATION.values.map(row => row.map(v => v.toFixed(2)));

    Plotly.newPlot(elementId, [{
        type: 'heatmap',
        z: CORRELATION.values,
        x: labels,
        y: labels,
        colorscale: [
            [0, '#ef4444'],
            [0.5, '#111111'],
            [1, '#60a5fa'],
        ],
        zmid: 0, zmin: -1, zmax: 1,
        text: text,
        texttemplate: '%{text}',
        textfont: { size: 9, color: '#999999' },
        hoverongaps: false,
        colorbar: { title: 'r', tickfont: { color: DARK.text } },
    }], darkLayout({
        xaxis: { tickangle: 45, side: 'bottom', gridcolor: DARK.grid, tickfont: { size: 10 } },
        yaxis: { autorange: 'reversed', gridcolor: DARK.grid, tickfont: { size: 10 } },
        margin: { l: 120, r: 80, t: 10, b: 120 },
    }), plotConfig);
}

// ── 3. Daily Price Profile ──────────────────────────────────

export function renderHourlyProfile(elementId) {
    const { hours, mean, std, min, max } = HOURLY_PROFILE;
    const labels = hours.map(h => `${String(h).padStart(2, '0')}:00`);

    // ±1 std band
    const upper = mean.map((m, i) => m + std[i]);
    const lower = mean.map((m, i) => Math.max(m - std[i], 0));

    Plotly.newPlot(elementId, [
        // Std band
        {
            x: [...labels, ...labels.slice().reverse()],
            y: [...upper, ...lower.slice().reverse()],
            fill: 'toself',
            fillcolor: 'rgba(96, 165, 250, 0.15)',
            line: { color: 'transparent' },
            name: '\u00b11 std',
            hoverinfo: 'skip',
        },
        // Min-max range (lighter)
        {
            x: [...labels, ...labels.slice().reverse()],
            y: [...max, ...min.slice().reverse()],
            fill: 'toself',
            fillcolor: 'rgba(96, 165, 250, 0.05)',
            line: { color: 'transparent' },
            name: 'min-max range',
            hoverinfo: 'skip',
        },
        // Mean line
        {
            x: labels,
            y: mean,
            type: 'scatter',
            mode: 'lines+markers',
            name: 'Mean price',
            line: { width: 3, color: '#60a5fa' },
            marker: { size: 5, color: '#60a5fa' },
            hovertemplate: '<b>%{x}</b><br>%{y:.0f} EUR/MWh<extra></extra>',
        },
    ], darkLayout({
        xaxis: { title: 'Hour of Day (Amsterdam)', gridcolor: DARK.grid, dtick: 2 },
        yaxis: { title: 'Price (EUR/MWh)', gridcolor: DARK.grid },
        legend: { orientation: 'h', y: 1.05, xanchor: 'center', x: 0.5 },
        margin: { l: 60, r: 30, t: 30, b: 50 },
    }), plotConfig);
}

// ── 4. Wind vs Price Scatter ────────────────────────────────

export function renderWindScatter(elementId) {
    Plotly.newPlot(elementId, [{
        x: WIND_VS_PRICE.wind,
        y: WIND_VS_PRICE.price,
        type: 'scatter',
        mode: 'markers',
        marker: {
            size: 5,
            color: WIND_VS_PRICE.price,
            colorscale: [[0, '#10b981'], [0.5, '#f59e0b'], [1, '#ef4444']],
            colorbar: { title: 'EUR/MWh', tickfont: { color: DARK.text } },
            opacity: 0.6,
        },
        hovertemplate: 'Wind: %{x:.1f} m/s<br>Price: %{y:.0f} EUR/MWh<extra></extra>',
    }], darkLayout({
        xaxis: { title: 'Offshore Wind Speed 80m (m/s)', gridcolor: DARK.grid },
        yaxis: { title: 'Price (EUR/MWh)', gridcolor: DARK.grid },
        margin: { l: 60, r: 80, t: 10, b: 50 },
    }), plotConfig);
}

// ── 5. MAE Over Time (live) ────────────────────────────────

function renderMaeOverTime(elementId, metricsHistory) {
    if (!metricsHistory || metricsHistory.length === 0) return;

    const dates = metricsHistory.map(e => e.date);
    const traces = [
        {
            x: dates,
            y: metricsHistory.map(e => e.update_mae),
            type: 'scatter',
            mode: 'lines+markers',
            name: 'Daily MAE',
            line: { width: 2, color: '#60a5fa' },
            marker: { size: 4, color: '#60a5fa' },
            hovertemplate: '<b>%{x}</b><br>Daily MAE: %{y:.1f} EUR/MWh<extra></extra>',
        },
        {
            x: dates,
            y: metricsHistory.map(e => e.last_week_mae),
            type: 'scatter',
            mode: 'lines',
            name: '7-day MAE',
            line: { width: 2, color: '#10b981', dash: 'dot' },
            hovertemplate: '<b>%{x}</b><br>7-day MAE: %{y:.1f} EUR/MWh<extra></extra>',
        },
    ];

    // Add vs Exchange MAE if any entries have it
    const exchangeDates = metricsHistory.filter(e => e.mae_vs_exchange != null);
    if (exchangeDates.length > 0) {
        traces.push({
            x: exchangeDates.map(e => e.date),
            y: exchangeDates.map(e => e.mae_vs_exchange),
            type: 'scatter',
            mode: 'lines+markers',
            name: 'vs Exchange MAE',
            line: { width: 2, color: '#f59e0b' },
            marker: { size: 4, color: '#f59e0b' },
            hovertemplate: '<b>%{x}</b><br>vs Exchange: %{y:.1f} EUR/MWh<extra></extra>',
        });
    }

    Plotly.newPlot(elementId, traces, darkLayout({
        xaxis: { title: 'Date', gridcolor: DARK.grid },
        yaxis: { title: 'MAE (EUR/MWh)', gridcolor: DARK.grid, rangemode: 'tozero' },
        legend: { orientation: 'h', y: 1.08, xanchor: 'center', x: 0.5 },
        margin: { l: 60, r: 30, t: 40, b: 50 },
    }), plotConfig);
}

// ── 6. Error Distribution (live) ──────────────────────────

function renderErrorDistribution(elementId, errorHistory) {
    if (!errorHistory || errorHistory.length === 0) return;

    Plotly.newPlot(elementId, [
        {
            x: errorHistory,
            type: 'histogram',
            marker: { color: 'rgba(96, 165, 250, 0.7)', line: { color: '#60a5fa', width: 1 } },
            nbinsx: 40,
            hovertemplate: 'Bin: %{x:.0f} EUR/MWh<br>Count: %{y}<extra></extra>',
        },
    ], darkLayout({
        xaxis: { title: 'Prediction Error (EUR/MWh)', gridcolor: DARK.grid },
        yaxis: { title: 'Count', gridcolor: DARK.grid },
        margin: { l: 50, r: 30, t: 10, b: 50 },
        shapes: [{
            type: 'line', x0: 0, x1: 0, y0: 0, y1: 1,
            yref: 'paper', line: { color: '#ef4444', width: 2, dash: 'dash' },
        }],
        annotations: [{
            x: 0, y: 1, yref: 'paper', text: 'zero',
            showarrow: false, font: { color: '#ef4444', size: 10 }, yanchor: 'bottom',
        }],
    }), plotConfig);
}

// ── 7. MAE by Hour of Day (live) ──────────────────────────

function renderMaeByHour(elementId, errorHistory, errorHours) {
    if (!errorHistory || !errorHours || errorHistory.length === 0) return;
    if (errorHistory.length !== errorHours.length) return;

    // Group absolute errors by hour
    const hourBuckets = Array.from({ length: 24 }, () => []);
    for (let i = 0; i < errorHistory.length; i++) {
        const hour = errorHours[i];
        if (hour >= 0 && hour < 24) {
            hourBuckets[hour].push(Math.abs(errorHistory[i]));
        }
    }

    const hours = Array.from({ length: 24 }, (_, i) => `${String(i).padStart(2, '0')}:00`);
    const maes = hourBuckets.map(b => b.length > 0 ? b.reduce((a, c) => a + c, 0) / b.length : 0);
    const counts = hourBuckets.map(b => b.length);

    Plotly.newPlot(elementId, [{
        x: hours,
        y: maes,
        type: 'bar',
        marker: {
            color: maes.map(v => v > 20 ? '#ef4444' : v > 15 ? '#f59e0b' : '#10b981'),
            opacity: 0.85,
        },
        hovertemplate: '<b>%{x}</b><br>MAE: %{y:.1f} EUR/MWh<br>Samples: %{customdata}<extra></extra>',
        customdata: counts,
    }], darkLayout({
        xaxis: { title: 'Hour of Day', gridcolor: DARK.grid, dtick: 2 },
        yaxis: { title: 'MAE (EUR/MWh)', gridcolor: DARK.grid, rangemode: 'tozero' },
        margin: { l: 50, r: 30, t: 10, b: 50 },
    }), plotConfig);
}

/**
 * Load live metrics from augur_forecast.json, update metric cards, and render performance charts.
 */
async function loadLiveMetrics() {
    try {
        const resp = await fetch('/data/augur_forecast.json');
        if (!resp.ok) return;
        const data = await resp.json();
        const m = data.metadata || {};
        const metrics = m.metrics || {};

        const set = (id, val) => {
            const el = document.getElementById(id);
            if (el && val != null) el.textContent = val;
        };

        set('metric-exchange-mae', metrics.vs_exchange?.mae_vs_exchange?.toFixed(1) || '--');
        set('metric-mae', metrics.update_mae?.toFixed(1) || '--');
        set('metric-samples', m.n_training_samples?.toLocaleString() || '--');

        // Render live performance charts
        renderMaeOverTime('maeOverTimeChart', m.metrics_history);
        renderErrorDistribution('errorDistChart', m.error_history);
        renderMaeByHour('maeByHourChart', m.error_history, m.error_hours);
    } catch {
        // Forecast not available yet
    }
}

/**
 * Render all model visualizations into their containers.
 */
export function renderAllModelViz() {
    renderFeatureImportance('featureImportanceChart');
    renderCorrelation('correlationChart');
    renderHourlyProfile('hourlyProfileChart');
    renderWindScatter('windScatterChart');
    loadLiveMetrics();
}
