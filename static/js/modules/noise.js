/**
 * Noise injection for data display
 * All numeric data is noised before display — the underlying APIs
 * are licensed and data cannot be redistributed as-is.
 * @module noise
 */

import { CONSTANTS } from './constants.js';

/**
 * Add random noise to a numeric value.
 * @param {number} value - Original value
 * @param {number} [percentage] - Noise range (default: CONSTANTS.NOISE_PERCENTAGE)
 * @returns {number} Noised value
 */
export function addNoise(value, percentage = CONSTANTS.NOISE_PERCENTAGE) {
    if (value === 0 || value === null || value === undefined) {
        return value;
    }
    const noisePercent = (Math.random() - 0.5) * percentage;
    return value * (1 + noisePercent);
}

/**
 * Add noise to all numeric values in a data object (timestamp -> value map).
 * @param {Object} data - Object with timestamp keys and numeric values
 * @param {number} [percentage] - Noise range
 * @returns {Object} New object with noised values
 */
export function addNoiseToDataset(data, percentage = CONSTANTS.NOISE_PERCENTAGE) {
    if (!data || typeof data !== 'object') {
        return data;
    }
    const noised = {};
    for (const [key, value] of Object.entries(data)) {
        noised[key] = typeof value === 'number' ? addNoise(value, percentage) : value;
    }
    return noised;
}
