/**
 * Web Vitals monitoring
 * Tracks Core Web Vitals: LCP, FID, CLS
 * @module web-vitals
 */

/**
 * Initialize Web Vitals monitoring
 * Logs metrics to console (can be extended to send to analytics)
 */
export function initWebVitals() {
    // Only run in browser
    if (typeof window === 'undefined') return;

    // Largest Contentful Paint (LCP)
    observeLCP();

    // First Input Delay (FID) - replaced by INP in newer browsers
    observeFID();

    // Cumulative Layout Shift (CLS)
    observeCLS();

    // Time to First Byte (TTFB)
    observeTTFB();
}

/**
 * Observe Largest Contentful Paint (LCP)
 * Good: < 2.5s, Needs Improvement: 2.5s - 4s, Poor: > 4s
 */
function observeLCP() {
    if (!('PerformanceObserver' in window)) return;

    try {
        const observer = new PerformanceObserver((list) => {
            const entries = list.getEntries();
            const lastEntry = entries[entries.length - 1];

            const lcp = lastEntry.renderTime || lastEntry.loadTime;
            const rating = lcp < 2500 ? 'good' : lcp < 4000 ? 'needs-improvement' : 'poor';

            console.log(`📊 LCP: ${lcp.toFixed(0)}ms [${rating}]`);
            logMetric('LCP', lcp, rating);
        });

        observer.observe({ type: 'largest-contentful-paint', buffered: true });
    } catch (error) {
        console.warn('LCP observation failed:', error);
    }
}

/**
 * Observe First Input Delay (FID)
 * Good: < 100ms, Needs Improvement: 100ms - 300ms, Poor: > 300ms
 */
function observeFID() {
    if (!('PerformanceObserver' in window)) return;

    try {
        const observer = new PerformanceObserver((list) => {
            const entries = list.getEntries();
            entries.forEach((entry) => {
                const fid = entry.processingStart - entry.startTime;
                const rating = fid < 100 ? 'good' : fid < 300 ? 'needs-improvement' : 'poor';

                console.log(`📊 FID: ${fid.toFixed(0)}ms [${rating}]`);
                logMetric('FID', fid, rating);
            });
        });

        observer.observe({ type: 'first-input', buffered: true });
    } catch (error) {
        console.warn('FID observation failed:', error);
    }
}

/**
 * Observe Cumulative Layout Shift (CLS)
 * Good: < 0.1, Needs Improvement: 0.1 - 0.25, Poor: > 0.25
 */
function observeCLS() {
    if (!('PerformanceObserver' in window)) return;

    try {
        let clsValue = 0;
        let clsEntries = [];

        const observer = new PerformanceObserver((list) => {
            const entries = list.getEntries();
            entries.forEach((entry) => {
                // Only count layout shifts without recent user input
                if (!entry.hadRecentInput) {
                    clsValue += entry.value;
                    clsEntries.push(entry);
                }
            });
        });

        observer.observe({ type: 'layout-shift', buffered: true });

        // Report CLS on page hide
        addEventListener('visibilitychange', () => {
            if (document.visibilityState === 'hidden') {
                const rating = clsValue < 0.1 ? 'good' : clsValue < 0.25 ? 'needs-improvement' : 'poor';
                console.log(`📊 CLS: ${clsValue.toFixed(3)} [${rating}] (${clsEntries.length} shifts)`);
                logMetric('CLS', clsValue, rating);
            }
        });
    } catch (error) {
        console.warn('CLS observation failed:', error);
    }
}

/**
 * Observe Time to First Byte (TTFB)
 * Good: < 800ms, Needs Improvement: 800ms - 1800ms, Poor: > 1800ms
 */
function observeTTFB() {
    if (!('performance' in window) || !performance.timing) return;

    try {
        // Use Navigation Timing API
        window.addEventListener('load', () => {
            const navTiming = performance.timing;
            const ttfb = navTiming.responseStart - navTiming.requestStart;
            const rating = ttfb < 800 ? 'good' : ttfb < 1800 ? 'needs-improvement' : 'poor';

            console.log(`📊 TTFB: ${ttfb.toFixed(0)}ms [${rating}]`);
            logMetric('TTFB', ttfb, rating);
        });
    } catch (error) {
        console.warn('TTFB observation failed:', error);
    }
}

/**
 * Log metric (extend this to send to analytics service)
 * @param {string} name - Metric name
 * @param {number} value - Metric value
 * @param {string} rating - Performance rating
 */
function logMetric(name, value, rating) {
    // Store in sessionStorage for debugging
    try {
        const metrics = JSON.parse(sessionStorage.getItem('webVitals') || '{}');
        metrics[name] = { value, rating, timestamp: Date.now() };
        sessionStorage.setItem('webVitals', JSON.stringify(metrics));
    } catch (error) {
        // Ignore storage errors
    }

    // TODO: Send to analytics service (Google Analytics, custom endpoint, etc.)
    // Example:
    // fetch('/api/vitals', {
    //     method: 'POST',
    //     body: JSON.stringify({ name, value, rating, url: location.href })
    // });
}

