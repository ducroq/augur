/**
 * Timezone display utilities.
 *
 * Data flowing into Plotly should be real UTC ISO strings; Plotly renders
 * them in the browser's local timezone. Do NOT mutate Date UTC fields to
 * encode local time — that was the convertUTCToAmsterdam pattern removed
 * with the fix for augur#16 (see chart-renderer.js for context).
 *
 * @module timezone-utils
 */

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
