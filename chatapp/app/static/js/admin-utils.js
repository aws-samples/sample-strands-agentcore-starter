/**
 * Admin Dashboard Shared Utilities
 * Common functions for time range filtering across admin pages
 */

/**
 * Calculate start time for a given number of days
 * @param {number} days - Number of days (1=Today, 7=7 Days, 30=30 Days)
 * @returns {Date} Start time set to midnight
 */
function calculateStartTime(days) {
    const startTime = new Date();
    // For "Today" (days=1), start at midnight today; otherwise go back (days-1) days to midnight
    const daysBack = days === 1 ? 0 : days - 1;
    startTime.setDate(startTime.getDate() - daysBack);
    startTime.setHours(0, 0, 0, 0);
    return startTime;
}

/**
 * Set time range and reload page with new parameters
 * @param {number} days - Number of days to look back (1=Today, 7=7 Days, 30=30 Days)
 * @param {string} [basePath] - Base URL path (defaults to current path)
 * @param {function} [paramsCallback] - Optional callback to add extra params
 */
function setTimeRange(days, basePath, paramsCallback) {
    const startTime = calculateStartTime(days);
    const params = new URLSearchParams(window.location.search);
    params.set('start_time', startTime.toISOString());
    params.delete('end_time'); // Don't set end_time - let backend use current time on each refresh

    if (paramsCallback) {
        paramsCallback(params);
    }

    const targetPath = basePath || window.location.pathname;
    window.location.href = `${targetPath}?${params.toString()}`;
}

/**
 * Apply custom date range from date inputs
 * @param {string} [basePath] - Base URL path (defaults to current path)
 * @param {function} [paramsCallback] - Optional callback to add extra params
 */
function applyCustomRange(basePath, paramsCallback) {
    const startDate = document.getElementById('start-date').value;
    const endDate = document.getElementById('end-date').value;
    if (!startDate || !endDate) return;

    const startTime = new Date(startDate + 'T00:00:00');
    const endTime = new Date(endDate + 'T23:59:59');

    if (startTime > endTime) {
        alert('Start date must be before end date');
        return;
    }

    const params = new URLSearchParams();
    params.set('start_time', startTime.toISOString());
    params.set('end_time', endTime.toISOString());

    if (paramsCallback) {
        paramsCallback(params);
    }

    const targetPath = basePath || window.location.pathname;
    window.location.href = `${targetPath}?${params.toString()}`;
}

/**
 * Highlight active time range preset button based on current date range
 */
function highlightActivePreset() {
    const startDateEl = document.getElementById('start-date');
    const endDateEl = document.getElementById('end-date');
    const presetButtons = document.getElementById('preset-buttons');

    if (!startDateEl || !endDateEl || !presetButtons) return;

    const startDateStr = startDateEl.value;
    const endDateStr = endDateEl.value;
    if (!startDateStr || !endDateStr) return;

    // Parse dates as local time (add T00:00:00 to avoid UTC interpretation)
    const start = new Date(startDateStr + 'T00:00:00');
    const end = new Date(endDateStr + 'T00:00:00');
    const today = new Date();
    today.setHours(0, 0, 0, 0);

    // Calculate days difference (add 1 because end date is inclusive)
    const daysDiff = Math.round((end - start) / (1000 * 60 * 60 * 24)) + 1;
    const isEndToday = end.toDateString() === today.toDateString();

    // Reset all buttons to default style
    presetButtons.querySelectorAll('button').forEach(btn => {
        btn.className = 'px-3 py-1.5 text-sm rounded-md bg-gray-100 hover:bg-gray-200 text-gray-700 transition-colors';
    });

    // Highlight active button based on days in range
    if (isEndToday) {
        let activeBtn = null;
        if (daysDiff === 1) activeBtn = document.getElementById('btn-1');
        else if (daysDiff >= 6 && daysDiff <= 8) activeBtn = document.getElementById('btn-7');
        else if (daysDiff >= 29 && daysDiff <= 31) activeBtn = document.getElementById('btn-30');

        if (activeBtn) {
            activeBtn.className = 'px-3 py-1.5 text-sm rounded-md bg-primary-100 text-primary-700 font-medium';
        }
    }
}

// Auto-initialize on DOM ready
document.addEventListener('DOMContentLoaded', highlightActivePreset);
