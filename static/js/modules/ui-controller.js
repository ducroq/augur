/**
 * UI controller for dashboard interface elements
 * @module ui-controller
 */

import { CONSTANTS, DATA_SOURCES } from './constants.js';
import { formatDateTime } from './timezone-utils.js';

/**
 * UI Controller class for managing dashboard interface
 */
export class UIController {
    constructor(dashboard) {
        this.dashboard = dashboard;
    }

    /**
     * Set up date/time range controls
     */
    setupDateTimeControls() {
        // Time range selector is now integrated with live data controls
        // Auto-apply on change
        document.getElementById('end-period')?.addEventListener('change', () => {
            this.dashboard.applySimpleRange();
        });
    }

    /**
     * Set up live data refresh controls
     */
    setupLiveDataControls() {
        const chartContainer = document.querySelector('.chart-container');
        if (chartContainer && !document.getElementById('refresh-live-data')) {
            const toggleContainer = document.createElement('div');
            toggleContainer.className = 'live-data-controls';
            toggleContainer.innerHTML = `
                <select id="end-period" aria-label="Forecast time range">
                    <option value="tomorrow">day-ahead</option>
                    <option value="dayaftertomorrow" selected>72-hour forecast</option>
                    <option value="week">week-ahead</option>
                </select>
                <button id="refresh-live-data" class="refresh-btn">🔄 Refresh</button>
            `;
            chartContainer.appendChild(toggleContainer);

            document.getElementById('refresh-live-data').addEventListener('click', async () => {
                await this.dashboard.handleRefreshClick();
            });
        }
    }

    /**
     * Position controls below the Plotly legend dynamically
     */
    positionControlsBelowLegend() {
        const controls = document.querySelector('.live-data-controls');
        if (!controls) {
            console.warn('Controls not found');
            return;
        }

        // Find the legend group in the Plotly SVG
        const legendGroup = document.querySelector('.legend');
        if (!legendGroup) {
            console.warn('Legend group not found');
            return;
        }

        try {
            // Get the bounding box of the legend
            const legendBox = legendGroup.getBBox();
            const legendTransform = legendGroup.getAttribute('transform');

            // Parse the transform to get x, y position
            const match = legendTransform?.match(/translate\(([^,]+),([^)]+)\)/);
            if (match) {
                const legendX = parseFloat(match[1]);
                const legendY = parseFloat(match[2]);

                // Get the legend background rect to find actual dimensions
                const legendBg = legendGroup.querySelector('.bg');
                const bgWidth = legendBg ? parseFloat(legendBg.getAttribute('width')) : legendBox.width;

                // Position controls below the legend, aligned to the right edge
                const verticalSpacing = 100;  // Increased spacing below legend
                const horizontalOffset = 20;   // Offset to the right
                const controlsWidth = controls.offsetWidth;

                // Align controls' right edge with legend's right edge
                const leftPos = legendX + bgWidth - controlsWidth + horizontalOffset;
                const topPos = legendY + legendBox.height + verticalSpacing;

                console.log('Positioning controls:', { legendX, legendY, bgWidth, controlsWidth, leftPos, topPos });

                controls.style.left = `${leftPos}px`;
                controls.style.top = `${topPos}px`;
                controls.style.right = ''; // Clear right positioning
            }
        } catch (e) {
            console.error('Could not position controls dynamically:', e);
        }
    }

    /**
     * Update info cards with energy data statistics
     * @param {Object} energyData - Energy forecast data
     */
    updateInfo(energyData) {
        // Last update time is now shown in chart title
        // This method can be used for other info updates in the future
    }


    /**
     * Show loading indicator
     */
    showLoadingIndicator() {
        const chartContainer = document.getElementById('energyChart');
        if (chartContainer) {
            chartContainer.style.opacity = '0.5';
            chartContainer.style.pointerEvents = 'none';
        }

        if (document.getElementById('loading-indicator')) return;

        const loadingDiv = document.createElement('div');
        loadingDiv.id = 'loading-indicator';
        loadingDiv.className = 'loading-indicator';
        loadingDiv.textContent = 'Loading data...';
        document.querySelector('.chart-container').appendChild(loadingDiv);
    }

    /**
     * Hide loading indicator
     */
    hideLoadingIndicator() {
        const chartContainer = document.getElementById('energyChart');
        if (chartContainer) {
            chartContainer.style.opacity = '1';
            chartContainer.style.pointerEvents = 'auto';
        }

        const loadingDiv = document.getElementById('loading-indicator');
        if (loadingDiv) {
            loadingDiv.remove();
        }
    }
}
