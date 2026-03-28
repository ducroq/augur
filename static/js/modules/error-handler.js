/**
 * Error handling and user notification utilities
 * @module error-handler
 */

/**
 * Classify and format errors with user-friendly messages
 *
 * @param {Error} error - The error to classify
 * @param {string} context - Context where error occurred (e.g., 'loading data')
 * @returns {Object} Error classification with user message
 */
export function classifyError(error, context = 'operation') {
    const errorInfo = {
        type: 'unknown',
        userMessage: '',
        technicalMessage: error.message || 'Unknown error',
        shouldRetry: false,
        severity: 'error'
    };

    // Network errors
    if (error.name === 'TypeError' && error.message.includes('fetch')) {
        errorInfo.type = 'network';
        errorInfo.userMessage = `Network connection failed while ${context}. Please check your internet connection.`;
        errorInfo.shouldRetry = true;
        errorInfo.severity = 'warning';
    }
    // HTTP errors
    else if (error.message && error.message.includes('HTTP')) {
        const statusMatch = error.message.match(/HTTP (\d+)/);
        const status = statusMatch ? parseInt(statusMatch[1]) : 0;

        errorInfo.type = 'http';
        if (status === 404) {
            errorInfo.userMessage = `Data not found while ${context}. The requested resource may not exist.`;
            errorInfo.shouldRetry = false;
        } else if (status === 429) {
            errorInfo.userMessage = `Too many requests while ${context}. Please wait a moment and try again.`;
            errorInfo.shouldRetry = true;
            errorInfo.severity = 'warning';
        } else if (status >= 500) {
            errorInfo.userMessage = `Server error while ${context}. The service may be temporarily unavailable.`;
            errorInfo.shouldRetry = true;
        } else {
            errorInfo.userMessage = `Request failed while ${context} (HTTP ${status}).`;
            errorInfo.shouldRetry = false;
        }
    }
    // JSON parsing errors
    else if (error instanceof SyntaxError || error.message.includes('JSON')) {
        errorInfo.type = 'parsing';
        errorInfo.userMessage = `Data format error while ${context}. The server returned invalid data.`;
        errorInfo.shouldRetry = false;
    }
    // Timeout errors
    else if (error.name === 'AbortError' || error.message.includes('timeout')) {
        errorInfo.type = 'timeout';
        errorInfo.userMessage = `Request timed out while ${context}. The server took too long to respond.`;
        errorInfo.shouldRetry = true;
        errorInfo.severity = 'warning';
    }
    // Generic errors
    else {
        errorInfo.userMessage = `An error occurred while ${context}. Please try again later.`;
        errorInfo.shouldRetry = true;
        errorInfo.severity = 'warning';
    }

    return errorInfo;
}

/**
 * Display user-friendly error notification
 *
 * @param {Object} errorInfo - Error classification from classifyError()
 */
export function showErrorNotification(errorInfo) {
    const existingNotification = document.getElementById('error-notification');
    if (existingNotification) {
        existingNotification.remove();
    }

    const notification = document.createElement('div');
    notification.id = 'error-notification';
    notification.className = `error-notification ${errorInfo.severity}`;
    const icon = document.createElement('div');
    icon.className = 'error-icon';
    icon.textContent = errorInfo.severity === 'error' ? '❌' : '⚠️';

    const content = document.createElement('div');
    content.className = 'error-content';
    const msg = document.createElement('div');
    msg.className = 'error-message';
    msg.textContent = errorInfo.userMessage;
    const tech = document.createElement('div');
    tech.className = 'error-technical';
    tech.textContent = `Technical: ${errorInfo.technicalMessage}`;
    content.appendChild(msg);
    content.appendChild(tech);

    const closeBtn = document.createElement('button');
    closeBtn.className = 'error-close';
    closeBtn.setAttribute('aria-label', 'Close');
    closeBtn.textContent = '\u00d7';
    closeBtn.addEventListener('click', () => notification.remove());

    notification.appendChild(icon);
    notification.appendChild(content);
    notification.appendChild(closeBtn);

    document.body.appendChild(notification);

    // Auto-remove after 10 seconds
    setTimeout(() => {
        if (notification.parentElement) {
            notification.remove();
        }
    }, 10000);
}
