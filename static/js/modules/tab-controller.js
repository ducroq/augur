/**
 * Tab navigation controller
 * @module tab-controller
 */

/**
 * Manages tab switching and lazy initialization of tab content.
 */
export class TabController {
    /**
     * @param {Function} onTabChange - Callback when tab changes: (tabKey) => void
     */
    constructor(onTabChange) {
        this.onTabChange = onTabChange;
        this.activeTab = 'prices';
        this.initializedTabs = new Set(['prices']); // Prices tab loads immediately
        this.init();
    }

    init() {
        const buttons = document.querySelectorAll('.tab-btn');
        buttons.forEach(btn => {
            btn.addEventListener('click', () => this.switchTab(btn.dataset.tab));
        });
    }

    /**
     * Switch to a tab by key.
     * @param {string} tabKey
     */
    switchTab(tabKey) {
        if (tabKey === this.activeTab) return;

        // Update button states
        document.querySelectorAll('.tab-btn').forEach(btn => {
            const isActive = btn.dataset.tab === tabKey;
            btn.classList.toggle('active', isActive);
            btn.setAttribute('aria-selected', isActive);
        });

        // Update panel visibility
        document.querySelectorAll('.tab-panel').forEach(panel => {
            panel.classList.toggle('active', panel.id === `panel-${tabKey}`);
        });

        this.activeTab = tabKey;

        // Resize any existing Plotly chart in the new panel (handles display:none -> block)
        const chartEl = this.getChartElement(tabKey);
        if (chartEl && chartEl.data) {
            Plotly.Plots.resize(chartEl);
        }

        // Notify dashboard to load data if needed
        const firstVisit = !this.initializedTabs.has(tabKey);
        this.initializedTabs.add(tabKey);
        this.onTabChange(tabKey, firstVisit);
    }

    /**
     * Get the chart DOM element for a tab.
     * @param {string} tabKey
     * @returns {HTMLElement|null}
     */
    getChartElement(tabKey) {
        const ids = {
            prices: 'energyChart',
            renewables: 'renewablesChart',
            grid: 'gridChart',
            weather: 'weatherChart',
            gas: 'gasChart',
        };
        return document.getElementById(ids[tabKey] || '');
    }
}
