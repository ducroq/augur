/**
 * Model explanation visualizations for the Model tab.
 * All charts use pre-computed data from model-viz-data.js.
 * @module model-viz
 */

import {
    CORRELATION, FEATURE_IMPORTANCE_BY_HORIZON, HOURLY_PROFILE,
    LEARNING_CURVE, WIND_VS_PRICE,
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
        type: 'scattergl',
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

// ── 5. Learning Curve ───────────────────────────────────────

export function renderLearningCurve(elementId) {
    Plotly.newPlot(elementId, [{
        x: LEARNING_CURVE.x,
        y: LEARNING_CURVE.y,
        type: 'scatter',
        mode: 'lines',
        line: { width: 2, color: '#a78bfa' },
        fill: 'tozeroy',
        fillcolor: 'rgba(167, 139, 250, 0.1)',
        hovertemplate: 'Sample %{x}<br>Rolling MAE: %{y:.1f} EUR/MWh<extra></extra>',
    }], darkLayout({
        xaxis: { title: 'Training Samples (rolling window)', gridcolor: DARK.grid },
        yaxis: { title: 'Rolling MAE (EUR/MWh)', gridcolor: DARK.grid },
        margin: { l: 60, r: 30, t: 10, b: 50 },
    }), plotConfig);
}

/**
 * Render all model visualizations into their containers.
 */
export function renderAllModelViz() {
    renderFeatureImportance('featureImportanceChart');
    renderCorrelation('correlationChart');
    renderHourlyProfile('hourlyProfileChart');
    renderWindScatter('windScatterChart');
    renderLearningCurve('learningCurveChart');
}
