/**
 * Admin Dashboard Shared Utilities
 * Common functions for time range filtering and timezone handling across admin pages
 */

/**
 * Calculate start time for a given number of days in user's local timezone
 * @param {number} days - Number of days (1=Today, 7=7 Days, 30=30 Days)
 * @returns {Date} Start time set to midnight local time
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
 * Format a UTC timestamp to local timezone
 * @param {string} utcTimestamp - ISO timestamp string (UTC)
 * @param {object} options - Formatting options
 * @param {boolean} options.includeDate - Include date portion (default: true)
 * @param {boolean} options.includeTime - Include time portion (default: true)
 * @param {boolean} options.includeSeconds - Include seconds (default: false)
 * @returns {string} Formatted local time string (MM/DD/YYYY HH:MM:SS AM/PM)
 */
function formatLocalTime(utcTimestamp, options = {}) {
    if (!utcTimestamp) return '';
    
    const { includeDate = true, includeTime = true, includeSeconds = false } = options;
    
    // Parse the UTC timestamp
    const date = new Date(utcTimestamp);
    if (isNaN(date.getTime())) return utcTimestamp;
    
    const parts = [];
    
    if (includeDate) {
        // Format: MM/DD/YYYY
        const month = String(date.getMonth() + 1).padStart(2, '0');
        const day = String(date.getDate()).padStart(2, '0');
        const year = date.getFullYear();
        parts.push(`${month}/${day}/${year}`);
    }
    
    if (includeTime) {
        // Format: HH:MM:SS AM/PM
        let hours = date.getHours();
        const minutes = String(date.getMinutes()).padStart(2, '0');
        const ampm = hours >= 12 ? 'PM' : 'AM';
        hours = hours % 12;
        hours = hours ? hours : 12; // 0 should be 12
        const hoursStr = String(hours).padStart(2, '0');
        
        let timeStr = `${hoursStr}:${minutes}`;
        if (includeSeconds) {
            const seconds = String(date.getSeconds()).padStart(2, '0');
            timeStr += `:${seconds}`;
        }
        timeStr += ` ${ampm}`;
        parts.push(timeStr);
    }
    
    return parts.join(' ');
}

/**
 * Convert all elements with data-utc-timestamp attribute to local time
 * Call this on page load to convert server-rendered UTC times to local
 */
function convertTimestampsToLocal() {
    document.querySelectorAll('[data-utc-timestamp]').forEach(el => {
        const utcTimestamp = el.dataset.utcTimestamp;
        const includeDate = el.dataset.includeDate !== 'false';
        const includeTime = el.dataset.includeTime !== 'false';
        const includeSeconds = el.dataset.includeSeconds === 'true';
        
        const localTime = formatLocalTime(utcTimestamp, { includeDate, includeTime, includeSeconds });
        if (localTime) {
            el.textContent = localTime;
        }
    });
}

/**
 * Format a date range display (e.g., "from X to Y")
 * @param {string} startUtc - Start timestamp (UTC)
 * @param {string} endUtc - End timestamp (UTC)
 * @returns {string} Formatted range string
 */
function formatLocalDateRange(startUtc, endUtc) {
    const startLocal = formatLocalTime(startUtc, { includeDate: true, includeTime: true });
    const endLocal = formatLocalTime(endUtc, { includeDate: true, includeTime: true });
    return `${startLocal} to ${endLocal}`;
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
 * Also updates date inputs to show local dates instead of UTC dates
 */
function highlightActivePreset() {
    const startDateEl = document.getElementById('start-date');
    const endDateEl = document.getElementById('end-date');
    const presetButtons = document.getElementById('preset-buttons');

    if (!startDateEl || !endDateEl) return;

    // Get the UTC timestamps from URL params and convert to local dates
    const params = new URLSearchParams(window.location.search);
    const startTimeParam = params.get('start_time');
    const endTimeParam = params.get('end_time');

    // Convert UTC timestamps to local date strings for the date inputs
    if (startTimeParam) {
        const startDate = new Date(startTimeParam);
        if (!isNaN(startDate.getTime())) {
            const localStartDate = `${startDate.getFullYear()}-${String(startDate.getMonth() + 1).padStart(2, '0')}-${String(startDate.getDate()).padStart(2, '0')}`;
            startDateEl.value = localStartDate;
        }
    }
    if (endTimeParam) {
        const endDate = new Date(endTimeParam);
        if (!isNaN(endDate.getTime())) {
            const localEndDate = `${endDate.getFullYear()}-${String(endDate.getMonth() + 1).padStart(2, '0')}-${String(endDate.getDate()).padStart(2, '0')}`;
            endDateEl.value = localEndDate;
        }
    } else {
        // No end_time means "now" - use today's date
        const today = new Date();
        const localToday = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
        endDateEl.value = localToday;
    }

    if (!presetButtons) return;

    const startDateStr = startDateEl.value;
    const endDateStr = endDateEl.value;
    if (!startDateStr || !endDateStr) return;

    // Parse dates as local time
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
document.addEventListener('DOMContentLoaded', () => {
    highlightActivePreset();
    convertTimestampsToLocal();
});
