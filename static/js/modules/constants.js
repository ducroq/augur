/**
 * Application constants and configuration
 * @module constants
 */

// Constants for unit conversions, intervals, and thresholds
export const CONSTANTS = {
    // Unit conversions
    EUR_KWH_TO_MWH_MULTIPLIER: 1000,

    // Refresh intervals
    LIVE_DATA_REFRESH_INTERVAL_MS: 10 * 60 * 1000, // 10 minutes

    // Data noise for educational purposes
    NOISE_PERCENTAGE: 0.1, // ±10%

    // Chart height
    CHART_HEIGHT: 600,

    // Default settings
    DEFAULT_PRICE_THRESHOLD: 0,
    MAX_HISTORICAL_DAYS: 30,
    DEFAULT_CHEAP_PRICE_THRESHOLD: 50, // EUR/MWh

    // Time periods in milliseconds
    ONE_HOUR_MS: 60 * 60 * 1000,
    ONE_DAY_MS: 24 * 60 * 60 * 1000
};

// Data source configuration
export const DATA_SOURCES = {
    // Historical data sources from energy_price_forecast.json
    forecast: [
        {
            key: 'entsoe',
            name: 'ENTSO-E',
            color: '#60a5fa',
            description: 'European Network of Transmission System Operators for Electricity'
        },
        {
            key: 'energy_zero',
            name: 'EnergyZero',
            color: '#10b981',
            description: 'Dutch energy provider day-ahead prices'
        },
        {
            key: 'epex',
            name: 'EPEX',
            color: '#f59e0b',
            description: 'European Power Exchange'
        },
        {
            key: 'elspot',
            name: 'Elspot',
            color: '#ef4444',
            description: 'Nord Pool day-ahead market'
        }
    ],

    // Tab configuration: which data files to load per tab
    tabs: {
        prices: {
            files: ['energy_price_forecast.json'],
        },
        forecast: {
            files: ['wind_forecast.json', 'solar_forecast.json', 'weather_forecast_multi_location.json'],
        },
        grid: {
            files: ['grid_imbalance.json', 'cross_border_flows.json', 'load_forecast.json'],
        },
        market: {
            files: ['market_proxies.json', 'gas_storage.json', 'gas_flows.json'],
        },
    },

    // Live Energy Zero data configuration
    energyZero: {
        name: {
            live: 'Energy Zero (Live)',
            historical: 'Energy Zero (Historical)'
        },
        color: '#0e4531ff',  // Dark green
        colorAlt: '#10b981',  // Alternative lighter green
        line: {
            width: 4,
            dash: 'solid'
        },
        marker: {
            size: 6,
            symbol: {
                live: 'diamond',
                historical: 'circle'
            },
            outline: {
                color: '#ffffff',
                width: 1
            }
        }
    }
};
