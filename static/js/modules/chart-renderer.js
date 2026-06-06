/**
 * Chart rendering utilities using Plotly.js
 * @module chart-renderer
 */

/**
 * Convert any ISO datetime string or Date into a NAIVE (no timezone-suffix)
 * ISO string representing the same absolute moment expressed in the BROWSER'S
 * local timezone. Plotly interprets naive ISO strings as local time, so by
 * stripping the timezone after converting to the local wall-clock, all chart
 * elements render at the user's actual clock-time regardless of the source
 * convention (UTC, CEST, or anything else with a parseable offset).
 *
 * This is the single conversion point — applied once at the rendering boundary
 * inside this module (now-line, axis range, and trace x-values via
 * `localizeTraces`). Data-processing code keeps using `new Date(ts)` for
 * sorting/filtering, which correctly handles absolute moments.
 *
 * Idempotent for naive input within the same locale: a string already in
 * local-naive form parses to the same Date and emits the same value.
 *
 * Reference: augur#16 supersession / ADR-008. This is the centralised version
 * of the convention "data carries real UTC; rendering surfaces browser-local".
 *
 * @param {string|Date} input - ISO datetime string or Date object
 * @returns {string} Naive ISO string ("YYYY-MM-DDTHH:mm:ss.SSS") in local time
 */
export function utcToLocalNaiveISO(input) {
    const d = input instanceof Date ? input : new Date(input);
    if (isNaN(d.getTime())) return String(input);  // pass invalid through unchanged
    const pad = (n, w = 2) => String(n).padStart(w, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T` +
           `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}.` +
           `${pad(d.getMilliseconds(), 3)}`;
}

/**
 * Map every trace's x array through `utcToLocalNaiveISO` so Plotly receives
 * a uniform local-naive x dimension across all sources. Non-array x values
 * (scalars, missing) pass through untouched.
 *
 * @param {Array} traces - Plotly traces
 * @returns {Array} Shallow-copied traces with localized x arrays
 */
export function localizeTraces(traces) {
    if (!Array.isArray(traces)) return traces;
    return traces.map(t => {
        if (!t || !Array.isArray(t.x)) return t;
        return { ...t, x: t.x.map(utcToLocalNaiveISO) };
    });
}

/**
 * Get the vertical line shape for the current time. Rendered in browser-local
 * via `utcToLocalNaiveISO` so it lands on the user's wall-clock position on
 * the now-localised axis.
 * @returns {Array} Plotly shapes array
 */
export function getCurrentTimeLineShape() {
    const currentTimeISO = utcToLocalNaiveISO(new Date());

    // Simple white line like the horizontal axis
    return [{
        type: 'line',
        x0: currentTimeISO,
        y0: 0,
        x1: currentTimeISO,
        y1: 1,
        yref: 'paper',
        line: {
            color: 'white',
            width: 1,
            dash: 'solid'
        },
        layer: 'above'
    }];
}

/**
 * Get Plotly chart layout configuration
 * @param {Date} startDateTime - Start of time range
 * @param {Date} endDateTime - End of time range
 * @param {string} lastUpdateTime - Last update timestamp
 * @returns {Object} Plotly layout object
 */
export function getChartLayout(startDateTime, endDateTime, lastUpdateTime) {
    const xaxis = {
        title: 'Time',
        gridcolor: 'rgba(255,255,255,0.1)',
        color: 'white',
        tickcolor: 'white'
    };

    // Set explicit x-axis range if start and end times are provided.
    // Convert through utcToLocalNaiveISO so the axis is in browser-local time,
    // matching the localized trace data and the now-line.
    if (startDateTime && endDateTime) {
        xaxis.range = [utcToLocalNaiveISO(startDateTime), utcToLocalNaiveISO(endDateTime)];
    }

    // Format title with last update time
    const titleText = lastUpdateTime
        ? `Last updated: ${new Date(lastUpdateTime).toLocaleString()}`
        : '';

    return {
        title: {
            text: titleText,
            font: { color: 'white', size: 14 }
        },
        paper_bgcolor: 'rgba(0,0,0,0)',
        plot_bgcolor: 'rgba(0,0,0,0.3)',
        font: { color: 'white' },
        xaxis: xaxis,
        yaxis: {
            title: 'Price (EUR/MWh)',
            gridcolor: 'rgba(255,255,255,0.1)',
            color: 'white',
            tickcolor: 'white'
        },
        margin: { l: 60, r: 30, t: 60, b: 60 },
        showlegend: true,
        legend: {
            font: { color: 'white' },
            bgcolor: 'rgba(0,0,0,0.3)',
            bordercolor: 'rgba(255,255,255,0.2)',
            borderwidth: 1
        },
        shapes: getCurrentTimeLineShape()
    };
}

/**
 * Get Plotly chart configuration
 * @returns {Object} Plotly config object
 */
export function getChartConfig() {
    return {
        responsive: true,
        displayModeBar: true,
        modeBarButtonsToRemove: ['pan2d', 'lasso2d', 'select2d'],
        displaylogo: false
    };
}

/**
 * Render or update the Plotly chart
 * @param {string} elementId - DOM element ID for the chart
 * @param {Array} traces - Plotly traces data
 * @param {boolean} chartInitialized - Whether chart has been rendered before
 * @param {Date} startDateTime - Start of time range
 * @param {Date} endDateTime - End of time range
 * @param {string} lastUpdateTime - Last update timestamp
 * @returns {boolean} New initialization state
 */
export function renderChart(elementId, traces, chartInitialized, startDateTime, endDateTime, lastUpdateTime) {
    const layout = getChartLayout(startDateTime, endDateTime, lastUpdateTime);
    const config = getChartConfig();

    // Normalise all trace x-values to browser-local naive ISO so they render
    // at the user's wall-clock positions. Source data may be UTC, CEST, or
    // anything else with a parseable offset — this is the single conversion
    // boundary, kept in the rendering layer so processing code stays
    // timezone-agnostic.
    const localizedTraces = localizeTraces(traces);

    const element = document.getElementById(elementId);

    // Use Plotly.react() for efficient updates after initial render
    if (chartInitialized) {
        Plotly.react(elementId, localizedTraces, layout, config);
    } else {
        Plotly.newPlot(elementId, localizedTraces, layout, config);
        chartInitialized = true;

        // Mark chart container as initialized (for progressive enhancement)
        if (element && element.parentElement) {
            element.parentElement.classList.add('chart-initialized');
        }
    }

    return chartInitialized;
}
