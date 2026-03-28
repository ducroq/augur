/**
 * Timezone conversion utilities
 * @module timezone-utils
 */

// Memoization cache for timezone conversions
const conversionCache = new Map();
const MAX_CACHE_SIZE = 500;

// Pre-create the formatter to avoid repeated instantiation
const amsterdamFormatter = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Europe/Amsterdam',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false
});

/**
 * Converts a UTC date to Europe/Amsterdam timezone accounting for DST.
 * Handles both CET (UTC+1, winter) and CEST (UTC+2, summer) automatically.
 * Uses memoization for performance when called repeatedly with same inputs.
 *
 * @param {Date} utcDate - The UTC date to convert
 * @returns {Date} Date with Amsterdam timezone offset applied
 */
export function convertUTCToAmsterdam(utcDate) {
    const timestamp = utcDate.getTime();

    // Check cache first
    if (conversionCache.has(timestamp)) {
        return new Date(conversionCache.get(timestamp));
    }

    // Use pre-created formatter
    const parts = amsterdamFormatter.formatToParts(utcDate);
    const get = type => parts.find(p => p.type === type).value;

    // Build a UTC timestamp from the Amsterdam time components
    const amsterdamAsUTC = new Date(`${get('year')}-${get('month')}-${get('day')}T${get('hour')}:${get('minute')}:${get('second')}Z`);

    // The difference between this and the actual UTC time is the timezone offset
    const offsetMs = amsterdamAsUTC.getTime() - utcDate.getTime();

    // Apply the offset to get the local time
    const result = new Date(timestamp + offsetMs);

    // Cache the result (evict oldest if cache is full)
    if (conversionCache.size >= MAX_CACHE_SIZE) {
        const firstKey = conversionCache.keys().next().value;
        conversionCache.delete(firstKey);
    }
    conversionCache.set(timestamp, result.getTime());

    return result;
}

/**
 * Format a date for display
 * @param {Date} date - Date to format
 * @returns {string} Formatted datetime string
 */
export function formatDateTime(date) {
    return date.toLocaleString('en-GB', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
}
