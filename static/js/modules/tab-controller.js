/**
 * Tab navigation controller
 * @module tab-controller
 */

/**
 * Manages tab switching and lazy initialization of tab content.
 */
export class TabController {
    /**
     * @param {Function} onTabChange - Callback when tab changes: (tabKey, firstVisit) => void
     */
    constructor(onTabChange) {
        this.onTabChange = onTabChange;
        this.activeTab = 'prices';
        this.initializedTabs = new Set(['prices']);
        this.init();
    }

    init() {
        const buttons = document.querySelectorAll('.tab-btn');
        buttons.forEach(btn => {
            btn.addEventListener('click', () => this.switchTab(btn.dataset.tab));
        });
    }

    switchTab(tabKey) {
        if (tabKey === this.activeTab) return;

        document.querySelectorAll('.tab-btn').forEach(btn => {
            const isActive = btn.dataset.tab === tabKey;
            btn.classList.toggle('active', isActive);
            btn.setAttribute('aria-selected', isActive);
        });

        document.querySelectorAll('.tab-panel').forEach(panel => {
            panel.classList.toggle('active', panel.id === `panel-${tabKey}`);
        });

        this.activeTab = tabKey;

        // Resize any Plotly charts in the new panel
        const chartEls = this.getChartElements(tabKey);
        for (const el of chartEls) {
            if (el && el.data) {
                Plotly.Plots.resize(el);
            }
        }

        const firstVisit = !this.initializedTabs.has(tabKey);
        this.initializedTabs.add(tabKey);
        this.onTabChange(tabKey, firstVisit);
    }

    /**
     * Get all chart DOM elements for a tab.
     * @param {string} tabKey
     * @returns {HTMLElement[]}
     */
    getChartElements(tabKey) {
        const map = {
            prices: ['energyChart'],
            forecast: ['windChart', 'solarChart', 'weatherTempChart', 'weatherCloudChart'],
            grid: ['imbalanceChart', 'flowsChart', 'loadChart'],
            market: ['gasChart'],
            model: ['featureImportanceChart', 'correlationChart', 'hourlyProfileChart', 'windScatterChart', 'learningCurveChart'],
        };
        return (map[tabKey] || []).map(id => document.getElementById(id)).filter(Boolean);
    }

    /**
     * Get the primary chart element for a tab (for simple tabs).
     */
    getChartElement(tabKey) {
        return this.getChartElements(tabKey)[0] || null;
    }
}
