/**
 * Main Energy Dashboard application
 * @module dashboard
 */

import { CONSTANTS, DATA_SOURCES } from './modules/constants.js';
import { debounce } from './modules/utils.js';
import { classifyError, showErrorNotification } from './modules/error-handler.js';
import { ApiClient } from './modules/api-client.js';
import { processEnergyDataForChart } from './modules/data-processor.js';
import { renderChart, getChartLayout, getChartConfig } from './modules/chart-renderer.js';
import { UIController } from './modules/ui-controller.js';
import { initWebVitals } from './modules/web-vitals.js';
import { TabController } from './modules/tab-controller.js';
import { DataLoader } from './modules/data-loader.js';
import {
    getWindLocations, processWind,
    getSolarLocations, processSolar,
    getWeatherLocations, processWeatherTemp, processWeatherCloud,
    processImbalance, processFlows, processLoad, processNedProduction, processNuclear,
    buildMarketCards, processGasChart,
} from './modules/tab-charts.js';
import { renderAllModelViz } from './modules/model-viz.js';

/**
 * Main Energy Dashboard class
 */
class EnergyDashboard {
    constructor() {
        this.energyData = null;
        this.energyZeroData = null;
        this.refreshInterval = null;
        this.chartInitialized = false;

        // Date/time selection properties - default to today 00:00 to day after tomorrow (48 hours)
        const now = new Date();
        this.startDateTime = new Date(now);
        this.startDateTime.setHours(0, 0, 0, 0);
        this.endDateTime = new Date(now.getTime() + (CONSTANTS.ONE_DAY_MS * 2));
        this.endDateTime.setHours(23, 59, 59, 999);
        this.customTimeRange = true;
        // Initialize API client, UI controller, data loader, and tabs
        this.apiClient = new ApiClient();
        this.uiController = new UIController(this);
        this.dataLoader = new DataLoader();

        // Debounced refresh function (500ms delay)
        this.debouncedRefresh = debounce(
            () => this.refreshDataAndChart(),
            500
        );

        this.init();
    }

    /**
     * Initialize the dashboard
     */
    async init() {
        // Set up tab controller
        this.tabController = new TabController((tabKey, firstVisit) => {
            this.onTabChange(tabKey, firstVisit);
        });

        await Promise.all([
            this.loadEnergyData(),
            this.loadEnergyZeroHistoricalData(),
            this.loadAugurForecast(),
        ]);

        this.uiController.setupLiveDataControls();
        this.uiController.setupDateTimeControls();
        this.setupLiveDataRefresh();
        this.updateChart();
        this.updateInfo();
    }

    /**
     * Load energy forecast data
     */
    async loadEnergyData() {
        this.energyData = await this.apiClient.loadEnergyData();
    }

    /**
     * Load current Energy Zero data
     */
    async loadEnergyZeroData() {
        this.energyZeroData = await this.apiClient.loadEnergyZeroData();
    }

    /**
     * Load Augur ML forecast (may not exist yet)
     */
    async loadAugurForecast() {
        try {
            const resp = await fetch('/data/augur_forecast.json');
            if (resp.ok) {
                this.augurForecast = await resp.json();
            }
        } catch {
            // Forecast not available yet — that's fine
            this.augurForecast = null;
        }
    }

    /**
     * Load historical Energy Zero data for date range
     */
    async loadEnergyZeroHistoricalData() {
        this.energyZeroData = await this.apiClient.loadEnergyZeroHistoricalData(
            this.startDateTime,
            this.endDateTime
        );
    }

    /**
     * Set up automatic live data refresh
     */
    setupLiveDataRefresh() {
        this.refreshInterval = setInterval(async () => {
            console.log('🔄 Refreshing Energy Zero data...');
            await this.loadEnergyZeroData();
            this.updateChart();
        }, CONSTANTS.LIVE_DATA_REFRESH_INTERVAL_MS);
    }


    /**
     * Handle manual refresh button click
     */
    async handleRefreshClick() {
        const btn = document.getElementById('refresh-live-data');
        btn.textContent = '⏳ Refreshing...';
        btn.disabled = true;

        await this.loadEnergyZeroData();
        this.updateChart();

        btn.textContent = '🔄 Refresh';
        btn.disabled = false;
    }

    /**
     * Apply simple range selection
     */
    applySimpleRange() {
        const endPeriod = document.getElementById('end-period').value;

        const now = new Date();
        let startTime, endTime;

        // Always start at 00:00 today
        startTime = new Date(now);
        startTime.setHours(0, 0, 0, 0);

        // Calculate end time
        switch (endPeriod) {
            case 'tomorrow':
                endTime = new Date(now.getTime() + CONSTANTS.ONE_DAY_MS);
                endTime.setHours(23, 59, 59, 999);
                break;
            case 'dayaftertomorrow':
                endTime = new Date(now.getTime() + (CONSTANTS.ONE_DAY_MS * 2));
                endTime.setHours(23, 59, 59, 999);
                break;
            case 'week':
                endTime = new Date(now.getTime() + 7 * CONSTANTS.ONE_DAY_MS);
                endTime.setHours(23, 59, 59, 999);
                break;
            default:
                endTime = new Date(now.getTime() + (CONSTANTS.ONE_DAY_MS * 2));
                endTime.setHours(23, 59, 59, 999);
                break;
        }

        this.startDateTime = startTime;
        this.endDateTime = endTime;
        this.customTimeRange = true;

        this.debouncedRefresh();
    }


    /**
     * Refresh data and update chart
     */
    async refreshDataAndChart() {
        // Cancel any pending requests from previous refresh
        this.apiClient.cancelAllRequests();

        this.uiController.showLoadingIndicator();

        try {
            if (this.customTimeRange && this.startDateTime && this.endDateTime) {
                await this.loadEnergyZeroHistoricalData();
            } else {
                await this.loadEnergyZeroData();
            }

            this.updateChart();
            this.updateInfo();
        } catch (error) {
            // Don't show error for aborted requests
            if (error.name === 'AbortError') {
                console.log('Refresh cancelled by user action');
                return;
            }

            console.error('Error refreshing data:', error);
            const errorInfo = classifyError(error, 'refreshing dashboard data');
            showErrorNotification(errorInfo);
            this.updateChart();
        } finally {
            this.uiController.hideLoadingIndicator();
        }
    }

    /**
     * Get time range cutoff for filtering data
     * @returns {Date} Cutoff date
     */
    getTimeRangeCutoff() {
        if (this.customTimeRange && this.startDateTime) {
            return this.startDateTime;
        }

        const now = new Date();
        // For 'all' timeRange, go back far enough to capture yesterday's Energy Zero data
        const cutoffs = {
            '24h': new Date(now.getTime() - CONSTANTS.ONE_DAY_MS),
            '48h': new Date(now.getTime() - 2 * CONSTANTS.ONE_DAY_MS),
            '7d': new Date(now.getTime() - 7 * CONSTANTS.ONE_DAY_MS),
            'all': new Date(now.getTime() - 7 * CONSTANTS.ONE_DAY_MS)  // Show last 7 days
        };

        // Return the appropriate cutoff, default to 'all' if timeRange not recognized
        return cutoffs[this.currentTimeRange] || cutoffs['all'];
    }

    /**
     * Update the chart with current data
     */
    updateChart() {
        const cutoffTime = this.getTimeRangeCutoff();
        const result = processEnergyDataForChart(
            this.energyData,
            this.energyZeroData,
            cutoffTime,
            this.customTimeRange,
            this.startDateTime,
            this.endDateTime,
            this.augurForecast
        );

        // Get last update time from energy data
        const lastUpdate = this.energyData?.entsoe?.metadata?.start_time || new Date().toISOString();

        this.allTimestamps = result.allTimestamps;
        this.chartInitialized = renderChart(
            'energyChart',
            result.traces,
            this.chartInitialized,
            this.startDateTime,
            this.endDateTime,
            lastUpdate
        );

        // Position controls below legend after chart finishes rendering
        const chartEl = document.getElementById('energyChart');
        if (chartEl) {
            chartEl.on('plotly_afterplot', () => {
                this.uiController.positionControlsBelowLegend();
            });
        }
    }

    /**
     * Update info cards
     */
    updateInfo() {
        this.uiController.updateInfo(this.energyData);
    }

    /**
     * Handle tab switch — load data and render for non-Prices tabs.
     */
    async onTabChange(tabKey, firstVisit) {
        if (tabKey === 'prices') return;

        // Model tab has no data files to load — delay to let panel become visible
        if (tabKey === 'model') {
            if (firstVisit) setTimeout(() => renderAllModelViz(), 50);
            return;
        }

        const tabConfig = DATA_SOURCES.tabs[tabKey];
        if (!tabConfig) return;

        if (firstVisit) {
            const files = await this.dataLoader.loadFiles(tabConfig.files);
            if (tabKey === 'forecast') {
                this.initForecastTab(files);
            } else if (tabKey === 'grid') {
                this.renderPlotlyChart('imbalanceChart', processImbalance(files));
                this.renderPlotlyChart('flowsChart', processFlows(files));
                this.renderPlotlyChart('loadChart', processLoad(files));
                this.renderPlotlyChart('nedProductionChart', processNedProduction(files));
                this.renderPlotlyChart('nuclearChart', processNuclear(files));
            } else if (tabKey === 'market') {
                this.renderMarketTab(files);
            }
        }
    }

    /**
     * Initialize the Forecast tab with 3 sub-charts and dropdowns.
     */
    initForecastTab(files) {
        // Wind
        const windLocs = getWindLocations(files);
        const windSelect = document.getElementById('wind-location');
        this.populateSelect(windSelect, windLocs, loc => loc.includes('NL'));
        windSelect.addEventListener('change', () => {
            this.renderPlotlyChart('windChart', processWind(files, windSelect.value));
        });
        if (windLocs.length > 0) {
            this.renderPlotlyChart('windChart', processWind(files, windSelect.value));
        }

        // Solar
        const solarLocs = getSolarLocations(files);
        const solarSelect = document.getElementById('solar-location');
        this.populateSelect(solarSelect, solarLocs, loc => loc.includes('NL'));
        solarSelect.addEventListener('change', () => {
            this.renderPlotlyChart('solarChart', processSolar(files, solarSelect.value));
        });
        if (solarLocs.length > 0) {
            this.renderPlotlyChart('solarChart', processSolar(files, solarSelect.value));
        }

        // Weather (two charts, one dropdown controls both)
        const weatherLocs = getWeatherLocations(files);
        const weatherSelect = document.getElementById('weather-location');
        this.populateSelect(weatherSelect, weatherLocs, loc => loc.includes('NL'));
        const renderWeather = () => {
            const loc = weatherSelect.value;
            this.renderPlotlyChart('weatherTempChart', processWeatherTemp(files, loc));
            this.renderPlotlyChart('weatherCloudChart', processWeatherCloud(files, loc));
        };
        weatherSelect.addEventListener('change', renderWeather);
        if (weatherLocs.length > 0) renderWeather();
    }

    /**
     * Populate a select element with locations, NL first.
     */
    populateSelect(select, locations, isPreferred) {
        select.innerHTML = '';
        const preferred = locations.filter(isPreferred);
        const others = locations.filter(l => !isPreferred(l));

        if (preferred.length > 0 && others.length > 0) {
            const nlGroup = document.createElement('optgroup');
            nlGroup.label = 'Netherlands';
            preferred.forEach(loc => {
                nlGroup.appendChild(new Option(loc.replace(/_/g, ' '), loc));
            });
            select.appendChild(nlGroup);

            const otherGroup = document.createElement('optgroup');
            otherGroup.label = 'International';
            others.forEach(loc => {
                otherGroup.appendChild(new Option(loc.replace(/_/g, ' '), loc));
            });
            select.appendChild(otherGroup);
        } else {
            locations.forEach(loc => {
                select.appendChild(new Option(loc.replace(/_/g, ' '), loc));
            });
        }
    }

    /**
     * Render the Market tab: summary cards + small gas chart.
     */
    renderMarketTab(files) {
        const cards = buildMarketCards(files);
        const container = document.getElementById('marketCards');
        if (cards.length > 0) {
            container.replaceChildren();
            for (const c of cards) {
                const card = document.createElement('div');
                card.className = 'market-card';
                const label = document.createElement('div');
                label.className = 'card-label';
                label.textContent = c.label;
                const value = document.createElement('div');
                value.className = 'card-value';
                value.textContent = c.value;
                const unit = document.createElement('div');
                unit.className = 'card-unit';
                unit.textContent = c.unit;
                card.append(label, value, unit);
                if (c.detail) {
                    const detail = document.createElement('div');
                    detail.className = 'card-detail';
                    detail.textContent = c.detail;
                    card.appendChild(detail);
                }
                container.appendChild(card);
            }
        } else {
            container.replaceChildren();
            const p = document.createElement('p');
            p.style.cssText = 'color:#999;text-align:center;padding:20px;';
            p.textContent = 'No market data available.';
            container.appendChild(p);
        }

        // Small gas storage chart below cards
        this.renderPlotlyChart('gasChart', processGasChart(files));
    }

    /**
     * Render a Plotly chart into an element from a processor result.
     */
    renderPlotlyChart(elementId, result) {
        const chartEl = document.getElementById(elementId);
        if (!chartEl) return;

        if (!result.traces || result.traces.length === 0) {
            chartEl.innerHTML = '<p style="color:#999;text-align:center;padding:40px;">No data available.</p>';
            return;
        }

        const hasSecondAxis = !!result.layout?.yaxis2;
        const layout = {
            paper_bgcolor: '#111111',
            plot_bgcolor: '#111111',
            font: { color: '#cccccc', family: '-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif' },
            xaxis: {
                type: 'date',
                gridcolor: '#333333',
                linecolor: '#333333',
            },
            yaxis: {
                gridcolor: '#333333',
                linecolor: '#333333',
                ...result.layout?.yaxis,
            },
            legend: {
                orientation: 'h',
                yanchor: 'bottom',
                y: 1.02,
                xanchor: 'center',
                x: 0.5,
            },
            margin: { l: 60, r: hasSecondAxis ? 80 : 30, t: 30, b: 50 },
            hovermode: 'x unified',
            annotations: [{
                text: 'Data includes ±5% random noise',
                xref: 'paper', yref: 'paper',
                x: 1, y: -0.12,
                showarrow: false,
                font: { size: 10, color: '#666666' },
                xanchor: 'right',
            }],
        };

        if (hasSecondAxis) {
            layout.yaxis2 = {
                gridcolor: 'rgba(0,0,0,0)',
                linecolor: '#333333',
                ...result.layout.yaxis2,
            };
        }

        const config = {
            responsive: true,
            displayModeBar: true,
            modeBarButtonsToRemove: ['lasso2d', 'select2d'],
        };

        const fallback = chartEl.querySelector('.chart-loading-fallback');
        if (fallback) fallback.remove();

        Plotly.newPlot(chartEl, result.traces, layout, config);
    }

    /**
     * Clean up resources
     */
    destroy() {
        if (this.refreshInterval) {
            clearInterval(this.refreshInterval);
        }
        this.chartInitialized = false;
    }
}

// Initialize dashboard when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    // Initialize Web Vitals monitoring
    initWebVitals();

    window.energyDashboard = new EnergyDashboard();
});

// Clean up on page unload
window.addEventListener('beforeunload', () => {
    if (window.energyDashboard) {
        window.energyDashboard.destroy();
    }
});
