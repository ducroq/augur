/**
 * API client for fetching energy data
 * @module api-client
 */

import { CONSTANTS } from './constants.js';
import { classifyError, showErrorNotification } from './error-handler.js';
import { processEnergyZeroData } from './data-processor.js';

/**
 * API Client class for managing energy data requests
 */
export class ApiClient {
    constructor() {
        // API response cache (URL -> {data, timestamp, accessCount})
        this.apiCache = new Map();
        this.cacheExpiryMs = 5 * 60 * 1000; // 5 minutes cache TTL
        this.maxCacheSize = 50; // Maximum number of cached entries
        this.cacheHits = 0;
        this.cacheMisses = 0;

        // Request cancellation tracking
        this.activeRequests = new Map(); // URL -> AbortController
    }

    /**
     * Cancel all active requests
     */
    cancelAllRequests() {
        let cancelCount = 0;
        for (const [url, controller] of this.activeRequests.entries()) {
            controller.abort();
            cancelCount++;
        }
        this.activeRequests.clear();
        if (cancelCount > 0) {
            console.log(`🚫 Cancelled ${cancelCount} active requests`);
        }
    }

    /**
     * Cancel a specific request by URL
     * @param {string} url - URL of request to cancel
     */
    cancelRequest(url) {
        const controller = this.activeRequests.get(url);
        if (controller) {
            controller.abort();
            this.activeRequests.delete(url);
            console.log(`🚫 Cancelled request: ${url.substring(0, 60)}...`);
        }
    }

    /**
     * Get cache statistics
     * @returns {Object} Cache stats
     */
    getCacheStats() {
        return {
            size: this.apiCache.size,
            hits: this.cacheHits,
            misses: this.cacheMisses,
            hitRate: this.cacheHits > 0 ? (this.cacheHits / (this.cacheHits + this.cacheMisses) * 100).toFixed(2) + '%' : '0%'
        };
    }

    /**
     * Evict least recently used cache entries if cache is full
     */
    evictLRU() {
        if (this.apiCache.size < this.maxCacheSize) {
            return;
        }

        // Find the entry with the oldest access time
        let oldestKey = null;
        let oldestTime = Infinity;

        for (const [key, value] of this.apiCache.entries()) {
            if (value.lastAccess < oldestTime) {
                oldestTime = value.lastAccess;
                oldestKey = key;
            }
        }

        if (oldestKey) {
            this.apiCache.delete(oldestKey);
            console.log(`🗑️ Evicted LRU cache entry: ${oldestKey.substring(0, 50)}...`);
        }
    }

    /**
     * Clean expired cache entries
     */
    cleanExpiredCache() {
        const now = Date.now();
        let removedCount = 0;

        for (const [key, value] of this.apiCache.entries()) {
            if (now - value.timestamp > this.cacheExpiryMs) {
                this.apiCache.delete(key);
                removedCount++;
            }
        }

        if (removedCount > 0) {
            console.log(`🧹 Cleaned ${removedCount} expired cache entries`);
        }
    }

    /**
     * Cached fetch wrapper for Energy Zero API calls.
     * Returns cached response if available and not expired (5 min TTL).
     * Uses LRU eviction when cache is full.
     *
     * @param {string} url - The API URL to fetch
     * @returns {Promise<Response>} The fetch response (cached or fresh)
     */
    async cachedFetch(url) {
        const now = Date.now();

        // Clean expired entries periodically (every 10 requests)
        if ((this.cacheHits + this.cacheMisses) % 10 === 0) {
            this.cleanExpiredCache();
        }

        const cached = this.apiCache.get(url);

        // Return cached response if valid and not expired
        if (cached && (now - cached.timestamp) < this.cacheExpiryMs) {
            this.cacheHits++;
            cached.lastAccess = now; // Update access time for LRU
            cached.accessCount = (cached.accessCount || 0) + 1;

            console.log(`📦 Cache HIT (${this.cacheHits}/${this.cacheHits + this.cacheMisses}): ${url.substring(0, 60)}...`);

            // Return a mock Response object with the cached data
            return {
                ok: true,
                json: async () => cached.data,
                status: 200,
                statusText: 'OK (cached)'
            };
        }

        // Cache miss or expired - fetch fresh data
        this.cacheMisses++;
        console.log(`🌐 Cache MISS (${this.cacheMisses}/${this.cacheHits + this.cacheMisses}): ${url.substring(0, 60)}...`);

        // Cancel any existing request for this URL
        if (this.activeRequests.has(url)) {
            this.activeRequests.get(url).abort();
        }

        // Create AbortController for this request
        const abortController = new AbortController();
        this.activeRequests.set(url, abortController);

        try {
            const response = await fetch(url, {
                signal: abortController.signal,
                // Add timeout of 30 seconds
                // Note: This doesn't cancel the request, just the promise
            });

            // Remove from active requests on completion
            this.activeRequests.delete(url);

            // Cache successful responses
            if (response.ok) {
                const data = await response.json();

                // Evict LRU entry if cache is full
                this.evictLRU();

                this.apiCache.set(url, {
                    data: data,
                    timestamp: now,
                    lastAccess: now,
                    accessCount: 1
                });

                console.log(`💾 Cached response (cache size: ${this.apiCache.size}/${this.maxCacheSize})`);

                // Return a mock Response with the data
                return {
                    ok: true,
                    json: async () => data,
                    status: response.status,
                    statusText: response.statusText
                };
            }

            return response;

        } catch (error) {
            // Remove from active requests on error
            this.activeRequests.delete(url);

            // Re-throw the error unless it was an abort
            if (error.name === 'AbortError') {
                console.log(`🚫 Request aborted: ${url.substring(0, 60)}...`);
                throw error;
            }

            console.error(`❌ Fetch error for ${url.substring(0, 60)}:`, error);
            throw error;
        }
    }

    /**
     * Load energy forecast data from local JSON
     * @returns {Promise<Object>} Energy forecast data
     */
    async loadEnergyData() {
        try {
            const timestamp = new Date().getTime();
            const response = await fetch(`/data/energy_price_forecast.json?t=${timestamp}`);

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const data = await response.json();
            console.log('Loaded fresh energy data:', data);
            return data;
        } catch (error) {
            console.error('Error loading energy data:', error);
            const errorInfo = classifyError(error, 'loading energy price forecast');
            showErrorNotification(errorInfo);
            return [];
        }
    }

    /**
     * Load current Energy Zero data (today + tomorrow + day after tomorrow if available)
     * @returns {Promise<Object>} Processed Energy Zero data
     */
    async loadEnergyZeroData() {
        try {
            const today = new Date();
            const tomorrow = new Date(today);
            tomorrow.setDate(tomorrow.getDate() + 1);
            const dayAfterTomorrow = new Date(today);
            dayAfterTomorrow.setDate(dayAfterTomorrow.getDate() + 2);

            // Fetch today, tomorrow, and day after tomorrow (full 48-hour forecast)
            const dates = [today, tomorrow, dayAfterTomorrow];
            const allPrices = [];

            for (const date of dates) {
                const startOfDay = new Date(date);
                startOfDay.setHours(0, 0, 0, 0);
                const endOfDay = new Date(date);
                endOfDay.setHours(23, 59, 59, 999);

                const fromDate = startOfDay.toISOString();
                const tillDate = endOfDay.toISOString();

                const url = `https://api.energyzero.nl/v1/energyprices?fromDate=${fromDate}&tillDate=${tillDate}&interval=4&usageType=1&inclBtw=false`;

                console.log(`Fetching Energy Zero data for: ${date.toDateString()}`);

                try {
                    const response = await this.cachedFetch(url);
                    if (response.ok) {
                        const data = await response.json();
                        if (data.Prices && data.Prices.length > 0) {
                            console.log(`✅ Loaded ${data.Prices.length} prices for ${date.toDateString()}`);
                            allPrices.push(...data.Prices);
                        } else {
                            console.log(`ℹ️ No prices available for ${date.toDateString()}`);
                        }
                    } else {
                        console.warn(`HTTP ${response.status} for ${date.toDateString()}: ${response.statusText}`);
                    }
                } catch (error) {
                    console.warn(`Failed for ${date.toDateString()}:`, error);
                }
            }

            if (allPrices.length > 0) {
                const combinedData = { Prices: allPrices };
                const processedData = processEnergyZeroData(combinedData);
                console.log(`✅ Total Energy Zero prices loaded: ${allPrices.length}`);
                return processedData;
            }

            // If we reach here, all attempts failed
            console.error('❌ No Energy Zero data available');
            const error = new Error('Unable to load Energy Zero data for today or tomorrow');
            const errorInfo = classifyError(error, 'loading live Energy Zero prices');
            errorInfo.userMessage = 'Live Energy Zero data is currently unavailable. Historical forecasts are still shown.';
            errorInfo.severity = 'warning';
            showErrorNotification(errorInfo);
            return null;

        } catch (error) {
            console.error('❌ Error loading Energy Zero data:', error);
            const errorInfo = classifyError(error, 'loading live Energy Zero prices');
            showErrorNotification(errorInfo);
            return null;
        }
    }

    /**
     * Load historical Energy Zero data for a date range
     * @param {Date} startDateTime - Start date
     * @param {Date} endDateTime - End date
     * @returns {Promise<Object>} Processed historical data
     */
    async loadEnergyZeroHistoricalData(startDateTime, endDateTime) {
        try {
            console.log(`Loading Energy Zero historical data from ${startDateTime.toDateString()} to ${endDateTime.toDateString()}`);

            const daysDiff = Math.ceil((endDateTime - startDateTime) / CONSTANTS.ONE_DAY_MS);

            if (daysDiff <= 1) {
                // Single day request
                const startOfDay = new Date(startDateTime);
                startOfDay.setHours(0, 0, 0, 0);
                const endOfDay = new Date(endDateTime);
                endOfDay.setHours(23, 59, 59, 999);

                const fromDate = startOfDay.toISOString();
                const tillDate = endOfDay.toISOString();

                const url = `https://api.energyzero.nl/v1/energyprices?fromDate=${fromDate}&tillDate=${tillDate}&interval=4&usageType=1&inclBtw=false`;
                console.log(`Single day URL: ${url}`);

                const response = await this.cachedFetch(url);

                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }

                const data = await response.json();
                return processEnergyZeroData(data, {
                    isHistorical: true,
                    startDateTime,
                    endDateTime
                });
            } else {
                // Multiple day requests - fetch in parallel for better performance
                const fetchPromises = [];
                const currentDate = new Date(startDateTime);

                while (currentDate <= endDateTime) {
                    const startOfDay = new Date(currentDate);
                    startOfDay.setHours(0, 0, 0, 0);
                    const endOfDay = new Date(currentDate);
                    endOfDay.setHours(23, 59, 59, 999);

                    const fromDate = startOfDay.toISOString();
                    const tillDate = endOfDay.toISOString();
                    const dateString = currentDate.toDateString();

                    const url = `https://api.energyzero.nl/v1/energyprices?fromDate=${fromDate}&tillDate=${tillDate}&interval=4&usageType=1&inclBtw=false`;

                    // Create fetch promise for this day
                    fetchPromises.push(
                        this.cachedFetch(url)
                            .then(response => {
                                if (response.ok) {
                                    return response.json();
                                } else {
                                    console.warn(`Failed for ${dateString}: HTTP ${response.status}`);
                                    return null;
                                }
                            })
                            .catch(error => {
                                console.warn(`Failed to load data for ${dateString}:`, error);
                                return null;
                            })
                    );

                    currentDate.setDate(currentDate.getDate() + 1);
                }

                // Fetch all days in parallel
                const results = await Promise.all(fetchPromises);

                // Combine all prices
                const allPrices = [];
                results.forEach(dayData => {
                    if (dayData && dayData.Prices) {
                        allPrices.push(...dayData.Prices);
                    }
                });

                const processedData = processEnergyZeroData({ Prices: allPrices }, {
                    isHistorical: true,
                    startDateTime,
                    endDateTime
                });

                console.log('✅ Loaded Energy Zero historical data:', processedData);
                return processedData;
            }

        } catch (error) {
            console.error('❌ Error loading Energy Zero historical data:', error);
            return null;
        }
    }
}
