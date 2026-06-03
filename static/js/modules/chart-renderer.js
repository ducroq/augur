/**
 * Chart rendering utilities using Plotly.js
 * @module chart-renderer
 */

/**
 * Get the vertical line shape for the current time.
 * Chart data is real UTC; Plotly renders UTC strings in the browser's local
 * timezone, so this line lands on the same axis as the data without any
 * pre-shift mutation. (Pre-2026-06-03 this used convertUTCToAmsterdam which
 * silently mutated the Date's UTC fields — root cause of augur#16.)
 * @returns {Array} Plotly shapes array
 */
export function getCurrentTimeLineShape() {
    const currentTimeISO = new Date().toISOString();

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

    // Set explicit x-axis range if start and end times are provided
    if (startDateTime && endDateTime) {
        xaxis.range = [startDateTime.toISOString(), endDateTime.toISOString()];
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

    const element = document.getElementById(elementId);

    // Use Plotly.react() for efficient updates after initial render
    if (chartInitialized) {
        Plotly.react(elementId, traces, layout, config);
    } else {
        Plotly.newPlot(elementId, traces, layout, config);
        chartInitialized = true;

        // Mark chart container as initialized (for progressive enhancement)
        if (element && element.parentElement) {
            element.parentElement.classList.add('chart-initialized');
        }
    }

    return chartInitialized;
}
