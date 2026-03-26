/**
 * Data processing and transformation utilities
 * @module data-processor
 */

import { CONSTANTS, DATA_SOURCES } from './constants.js';
import { convertUTCToAmsterdam } from './timezone-utils.js';
import { addNoise } from './noise.js';

/**
 * Process Energy Zero API response data
 * @param {Object} rawData - Raw API response
 * @param {Object} options - Processing options
 * @returns {Object} Processed data structure
 */
export function processEnergyZeroData(rawData, options = {}) {
    if (!rawData || !rawData.Prices) {
        return null;
    }

    const {
        isHistorical = false,
        startDateTime = null,
        endDateTime = null,
        detectCurrentPrice = true
    } = options;

    const currentTime = new Date();
    const currentHour = new Date(currentTime.getFullYear(), currentTime.getMonth(),
                               currentTime.getDate(), currentTime.getHours());

    const processedData = {
        current_price: null,
        today_prices: [],
        statistics: {},
        last_updated: new Date().toISOString()
    };

    // Add time_range if historical
    if (isHistorical && startDateTime && endDateTime) {
        processedData.time_range = {
            start: startDateTime.toISOString(),
            end: endDateTime.toISOString()
        };
    }

    rawData.Prices.forEach(pricePoint => {
        const utcTimestamp = new Date(pricePoint.readingDate);
        const localTimestamp = convertUTCToAmsterdam(utcTimestamp);

        // Filter by time range if specified
        if (startDateTime && endDateTime) {
            if (localTimestamp < startDateTime || localTimestamp > endDateTime) {
                return; // Skip this price point
            }
        }

        const priceEurMwh = pricePoint.price * CONSTANTS.EUR_KWH_TO_MWH_MULTIPLIER;

        const hourData = {
            timestamp: localTimestamp.toISOString(),
            hour: localTimestamp.getHours(),
            price_eur_kwh: pricePoint.price,
            price_eur_mwh: priceEurMwh,
            reading_date: pricePoint.readingDate
        };

        // Add optional fields for historical data
        if (isHistorical) {
            hourData.date = localTimestamp.toISOString().split('T')[0];
            hourData.utc_timestamp = utcTimestamp.toISOString();
        }

        processedData.today_prices.push(hourData);

        // Detect current price if enabled
        if (detectCurrentPrice && localTimestamp.getTime() === currentHour.getTime()) {
            processedData.current_price = hourData;
        }
    });

    // Calculate statistics
    if (processedData.today_prices.length > 0) {
        const prices = processedData.today_prices.map(p => p.price_eur_mwh);
        processedData.statistics = {
            min: Math.min(...prices),
            max: Math.max(...prices),
            avg: prices.reduce((a, b) => a + b, 0) / prices.length,
            count: prices.length
        };
    }

    return processedData;
}

/**
 * Process energy forecast data for chart rendering
 * @param {Object} energyData - Energy forecast data
 * @param {Object} energyZeroData - Live Energy Zero data
 * @param {Date} cutoffTime - Time range cutoff
 * @param {boolean} customTimeRange - Whether using custom time range
 * @param {Date} startDateTime - Start of custom range
 * @param {Date} endDateTime - End of custom range
 * @returns {Array} Plotly traces
 */
export function processEnergyDataForChart(energyData, energyZeroData, cutoffTime, customTimeRange, startDateTime, endDateTime, augurForecast) {
    if (!energyData) {
        return [];
    }

    const traces = [];
    const dataSources = DATA_SOURCES.forecast;
    let allTimestamps = [];

    // Process forecast data sources
    dataSources.forEach(source => {
        if (energyData[source.key] && energyData[source.key].data) {
            const sourceData = energyData[source.key].data;
            const metadata = energyData[source.key].metadata;

            let multiplier = 1;
            if (metadata && metadata.units) {
                const units = metadata.units.toLowerCase();
                if (units.includes('kwh') || units.includes('eur/kwh')) {
                    multiplier = 1000;
                }
            }

            const dataPoints = Object.entries(sourceData).map(([datetime, price]) => {
                let normalizedDatetime = datetime;

                // Handle incorrect timezone offsets from various APIs
                // Some APIs return +00:18 or +00:09 instead of proper +02:00 (CEST) or +01:00 (CET)
                // The time portion is already in Amsterdam local time, just the offset indicator is wrong
                if (datetime.includes('+00:18') || datetime.includes('+00:09')) {
                    // Determine if we're in CEST (summer, +02:00) or CET (winter, +01:00)
                    // Quick check: parse the date portion to determine DST
                    const dateMatch = datetime.match(/^(\d{4})-(\d{2})-(\d{2})/);
                    if (dateMatch) {
                        const year = parseInt(dateMatch[1]);
                        const month = parseInt(dateMatch[2]);

                        // Rough DST check: Mar-Oct is typically CEST (+02:00), Nov-Feb is CET (+01:00)
                        // This is simplified; actual DST transitions happen on specific Sundays
                        const isDST = month >= 3 && month <= 10;
                        const correctOffset = isDST ? '+02:00' : '+01:00';

                        normalizedDatetime = datetime.replace(/\+00:(18|09)/, correctOffset);
                    }
                }

                const noisyPrice = addNoise(price * multiplier);

                return {
                    datetime: normalizedDatetime,
                    price: noisyPrice
                };
            });

            const filteredData = dataPoints.filter(item => {
                const itemDate = new Date(item.datetime);
                return itemDate >= cutoffTime;
            });

            if (filteredData.length > 0) {
                filteredData.sort((a, b) => new Date(a.datetime) - new Date(b.datetime));

                const xValues = filteredData.map(item => item.datetime);
                const yValues = filteredData.map(item => item.price);

                allTimestamps.push(...xValues);

                traces.push({
                    x: xValues,
                    y: yValues,
                    type: 'scatter',
                    mode: 'lines+markers',
                    name: source.name,
                    line: {
                        width: 3,
                        color: source.color
                    },
                    marker: {
                        size: 5,
                        color: source.color
                    },
                    hovertemplate: `<b>${source.name}</b><br>%{x}<br>Price: €%{y:.2f}/MWh<extra></extra>`
                });
            }
        }
    });

    // Add Energy Zero data if available
    if (energyZeroData && energyZeroData.today_prices) {
        let filteredPrices = energyZeroData.today_prices;

        if (customTimeRange && startDateTime && endDateTime) {
            filteredPrices = energyZeroData.today_prices.filter(item => {
                const itemDate = new Date(item.timestamp);
                return itemDate >= startDateTime && itemDate <= endDateTime;
            });
        } else if (!customTimeRange) {
            filteredPrices = energyZeroData.today_prices.filter(item => {
                const itemDate = new Date(item.timestamp);
                return itemDate >= cutoffTime;
            });
        }

        if (filteredPrices.length > 0) {
            filteredPrices.sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));

            const xValues = filteredPrices.map(item => item.timestamp);
            const yValues = filteredPrices.map(item => item.price_eur_mwh);

            const config = DATA_SOURCES.energyZero;

            // Determine if this is truly historical data (looking at past days only)
            const now = new Date();
            const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate());
            const isHistoricalOnly = startDateTime && startDateTime < todayStart && endDateTime && endDateTime < now;

            const displayName = isHistoricalOnly ? config.name.historical : config.name.live;
            const markerSymbol = isHistoricalOnly ? config.marker.symbol.historical : config.marker.symbol.live;

            traces.push({
                x: xValues,
                y: yValues,
                type: 'scatter',
                mode: 'lines+markers',
                name: displayName,
                line: {
                    width: config.line.width,
                    color: config.color,
                    dash: config.line.dash
                },
                marker: {
                    size: config.marker.size,
                    color: config.color,
                    symbol: markerSymbol,
                    line: {
                        color: config.marker.outline.color,
                        width: config.marker.outline.width
                    }
                },
                hovertemplate: `<b>${displayName}</b><br>%{x}<br>Price: €%{y:.2f}/MWh<extra></extra>`
            });

            allTimestamps.push(...xValues);
        }
    }

    // Add Augur ML forecast with confidence band if available
    if (augurForecast && augurForecast.forecast) {
        const tsFilter = (ts) => new Date(ts) >= cutoffTime;
        const sortByTs = (a, b) => new Date(a.ts) - new Date(b.ts);
        const now = new Date();

        const forecastData = Object.entries(augurForecast.forecast)
            .filter(([ts]) => tsFilter(ts))
            .map(([ts, price]) => ({ ts, price: addNoise(price) }))
            .sort(sortByTs);

        if (forecastData.length > 0) {
            // Confidence band only for future hours
            const upper = augurForecast.forecast_upper || {};
            const lower = augurForecast.forecast_lower || {};
            const bandX = [];
            const bandY = [];

            const futureTs = forecastData.filter(d => new Date(d.ts) >= now).map(d => d.ts);
            for (const ts of futureTs) {
                if (upper[ts] != null) {
                    bandX.push(ts);
                    bandY.push(addNoise(upper[ts]));
                }
            }
            for (let i = futureTs.length - 1; i >= 0; i--) {
                const ts = futureTs[i];
                if (lower[ts] != null) {
                    bandX.push(ts);
                    bandY.push(Math.max(addNoise(lower[ts]), 0));
                }
            }

            if (bandX.length > 0) {
                traces.push({
                    x: bandX,
                    y: bandY,
                    type: 'scatter',
                    fill: 'toself',
                    fillcolor: 'rgba(167, 139, 250, 0.15)',
                    line: { color: 'transparent' },
                    name: '80% confidence',
                    showlegend: true,
                    hoverinfo: 'skip',
                });
            }

            // Forecast line on top
            traces.push({
                x: forecastData.map(d => d.ts),
                y: forecastData.map(d => d.price),
                type: 'scatter',
                mode: 'lines',
                name: 'Augur ML Forecast',
                line: { width: 3, color: '#a78bfa', dash: 'dash' },
                hovertemplate: '<b>Augur ML</b><br>%{x}<br>Price: €%{y:.2f}/MWh<extra></extra>',
            });
            allTimestamps.push(...forecastData.map(d => d.ts));
        }
    }

    return { traces, allTimestamps: [...new Set(allTimestamps)].sort() };
}
