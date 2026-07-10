/* ============================================================
   app.js — Smart Farm Dashboard
   ============================================================ */

// ─── CONFIGURATION ──────────────────────────────────────────────
const CONFIG = {
    // Render backend URL
    API_BASE: 'https://smartfarm-4z48.onrender.com',
    DEVICE_ID: 'esp32_001',
    REFRESH_INTERVAL_MS: 30000, // 30 seconds
    MAX_ADVISORIES: 50,
};

// ─── STATE ──────────────────────────────────────────────────────
let chartInstances = {
    temp: null,
    humidity: null,
    rainfall: null,
};

let currentData = {
    readings: [],
    deviceId: '',
    count: 0,
};

let refreshTimer = null;
let isFirstLoad = true;

// ─── DOM REFS ──────────────────────────────────────────────────
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const dom = {
    deviceId: $('#device-id-display'),
    tempValue: $('#temp-value'),
    humidityValue: $('#humidity-value'),
    rainfallValue: $('#rainfall-value'),
    advisoryValue: $('#advisory-value'),
    lastUpdated: $('#last-updated'),
    statusDot: $('#status-dot'),
    refreshLabel: $('#refresh-label'),
    advisoryBody: $('#advisories-body'),
    advisoryCount: $('#advisory-count'),
    tempChart: $('#temp-chart'),
    humidityChart: $('#humidity-chart'),
    rainfallChart: $('#rainfall-chart'),
};

// ─── HELPERS ────────────────────────────────────────────────────

/** Format a date string for display */
function formatDate(dateStr) {
    if (!dateStr) return '—';
    try {
        const d = new Date(dateStr);
        if (isNaN(d.getTime())) return dateStr;
        return d.toLocaleString('en-US', {
            month: 'short',
            day: 'numeric',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
        });
    } catch (_) {
        return dateStr;
    }
}

/** Format a date for table (shorter) */
function formatDateShort(dateStr) {
    if (!dateStr) return '—';
    try {
        const d = new Date(dateStr);
        if (isNaN(d.getTime())) return dateStr;
        return d.toLocaleString('en-US', {
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
        });
    } catch (_) {
        return dateStr;
    }
}

/** Get advisory CSS class based on label */
function getAdvisoryClass(label) {
    if (!label) return 'info';
    const l = label.toLowerCase();
    if (l.includes('optimal') || l.includes('excellent') || l.includes('good')) return 'optimal';
    if (l.includes('critical') || l.includes('severe') || l.includes('danger') || l.includes('high risk')) return 'critical';
    if (l.includes('warning') || l.includes('caution') || l.includes('moderate')) return 'warning';
    if (l.includes('monitor') || l.includes('watch') || l.includes('check')) return 'monitor';
    return 'info';
}

/** Truncate advisory label for display */
function truncateAdvisory(label, maxLen = 60) {
    if (!label) return '—';
    return label.length > maxLen ? label.slice(0, maxLen) + '…' : label;
}

// ─── API ────────────────────────────────────────────────────────

/** Fetch historical data from the backend */
async function fetchHistoryData() {
    const url =
        `${CONFIG.API_BASE}/history-data?device_id=${encodeURIComponent(CONFIG.DEVICE_ID)}`;
    try {
        const resp = await fetch(url);
        if (!resp.ok) {
            throw new Error(`HTTP ${resp.status}`);
        }
        const json = await resp.json();
        return json;
    } catch (err) {
        console.warn('[fetchHistoryData]', err.message);
        return null;
    }
}

// ─── RENDER — CARDS ────────────────────────────────────────────

/** Update the four sensor cards from the most recent reading */
function renderCards(readings) {
    if (!readings || readings.length === 0) {
        dom.tempValue.textContent = '--';
        dom.humidityValue.textContent = '--';
        dom.rainfallValue.textContent = '--';
        dom.advisoryValue.innerHTML = `<span class="no-data-text">No data</span>`;
        return;
    }

    const latest = readings[0]; // already sorted desc by fetch
    const input = latest.input || {};

    // Temperature
    const temp = input.temp_mean;
    dom.tempValue.textContent = temp !== undefined && temp !== null ? Number(temp).toFixed(1) : '--';

    // Humidity
    const hum = input.humidity_mean;
    dom.humidityValue.textContent = hum !== undefined && hum !== null ? Number(hum).toFixed(0) : '--';

    // Rainfall
    const rain = input.precipitation_mm;
    dom.rainfallValue.textContent = rain !== undefined && rain !== null ? Number(rain).toFixed(1) : '--';

    // Advisory
    const label = latest.advisory_label || 'No advisory';
    const cls = getAdvisoryClass(label);
    dom.advisoryValue.innerHTML = `
            <span class="advisory-badge ${cls}">${truncateAdvisory(label, 50)}</span>
        `;
}

// ─── RENDER — TABLE ────────────────────────────────────────────

/** Render the recent advisories table in reverse chronological order */
function renderTable(readings) {
    const tbody = dom.advisoryBody;
    const countEl = dom.advisoryCount;

    if (!readings || readings.length === 0) {
        tbody.innerHTML = `<tr class="empty-row"><td colspan="2">No advisory data available</td></tr>`;
        countEl.textContent = '0 advisories';
        return;
    }

    // Show all readings, already sorted desc by predicted_at
    const rows = readings.slice(0, CONFIG.MAX_ADVISORIES);
    countEl.textContent = `${rows.length} advisory${rows.length !== 1 ? 'ies' : ''}`;

    let html = '';
    for (const r of rows) {
        const date = formatDateShort(r.predicted_at);
        const label = r.advisory_label || '—';
        const cls = getAdvisoryClass(label);
        html += `
                <tr>
                    <td class="date-cell">${date}</td>
                    <td><span class="advisory-tag ${cls}">${truncateAdvisory(label, 70)}</span></td>
                </tr>
            `;
    }
    tbody.innerHTML = html;
}

// ─── RENDER — CHARTS ───────────────────────────────────────────

/** Create or update a Chart.js line chart */
function updateOrCreateChart(canvasId, label, color, dataPoints, unit = '') {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return null;

    // Prepare data
    const sorted = [...dataPoints].reverse(); // chronological for charts
    const labels = sorted.map((d) => {
        const dt = new Date(d.predicted_at);
        return dt.toLocaleString('en-US', { hour: '2-digit', minute: '2-digit', month: 'short', day: 'numeric' });
    });

    let values;
    switch (canvasId) {
        case 'temp-chart':
            values = sorted.map((d) => d.input?.temp_mean ?? null);
            break;
        case 'humidity-chart':
            values = sorted.map((d) => d.input?.humidity_mean ?? null);
            break;
        case 'rainfall-chart':
            values = sorted.map((d) => d.input?.precipitation_mm ?? null);
            break;
        default:
            values = [];
    }

    const hasData = values.some((v) => v !== null && v !== undefined);

    // If existing chart, update it
    if (chartInstances[canvasId]) {
        const chart = chartInstances[canvasId];
        chart.data.labels = labels;
        chart.data.datasets[0].data = values;
        chart.update('none');
        return chart;
    }

    // Otherwise create new chart
    const ctx = canvas.getContext('2d');

    // Gradient fill
    const gradient = ctx.createLinearGradient(0, 0, 0, 180);
    const alpha = 0.25;
    gradient.addColorStop(0, color + Math.round(alpha * 255).toString(16).padStart(2, '0'));
    gradient.addColorStop(1, color + '00');

    const newChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: label,
                data: values,
                borderColor: color,
                backgroundColor: gradient,
                fill: true,
                tension: 0.3,
                pointRadius: 2.5,
                pointBackgroundColor: color,
                borderWidth: 2.5,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: false,
                },
                tooltip: {
                    callbacks: {
                        label: function(ctx) {
                            let val = ctx.parsed.y;
                            if (val === null || val === undefined) return 'No data';
                            return `${Number(val).toFixed(1)} ${unit}`.trim();
                        },
                    },
                },
            },
            scales: {
                x: {
                    grid: { display: false },
                    ticks: {
                        maxTicksLimit: 8,
                        font: { size: 9 },
                        color: '#8a9a8a',
                    },
                },
                y: {
                    grid: { color: 'rgba(0,0,0,0.05)' },
                    ticks: {
                        font: { size: 9 },
                        color: '#8a9a8a',
                        callback: function(value) {
                            return Number(value).toFixed(0);
                        },
                    },
                    beginAtZero: canvasId === 'rainfall-chart' ? true : undefined,
                },
            },
            interaction: {
                intersect: false,
                mode: 'index',
            },
        },
    });

    chartInstances[canvasId] = newChart;
    return newChart;
}

/** Update all charts with current data */
function renderCharts(readings) {
    const data = readings || [];

    // Colors
    const colors = {
        temp: '#e65100',
        humidity: '#0d47a1',
        rainfall: '#00695c',
    };

    updateOrCreateChart('temp-chart', 'Temperature', colors.temp, data, '°C');
    updateOrCreateChart('humidity-chart', 'Humidity', colors.humidity, data, '%');
    updateOrCreateChart('rainfall-chart', 'Rainfall', colors.rainfall, data, 'mm');
}

// ─── MAIN UPDATE ───────────────────────────────────────────────

/** Fetch data and update the entire dashboard */
async function refreshDashboard() {
    try {
        // Show loading state on first load
        if (isFirstLoad) {
            dom.tempValue.textContent = '…';
            dom.humidityValue.textContent = '…';
            dom.rainfallValue.textContent = '…';
            dom.advisoryValue.innerHTML = `<span class="no-data-text">Loading…</span>`;
        }

        const result = await fetchHistoryData();

        if (!result || !result.readings || result.readings.length === 0) {
            // No data — show empty state
            currentData = { readings: [], deviceId: result?.device_id || CONFIG.DEVICE_ID, count: 0 };
            renderCards([]);
            renderTable([]);
            renderCharts([]);
            dom.lastUpdated.textContent = new Date().toLocaleString();
            dom.statusDot.className = 'dot paused';
            if (isFirstLoad) {
                dom.advisoryValue.innerHTML = `<span class="no-data-text">No data available</span>`;
            }
            isFirstLoad = false;
            return;
        }

        // Sort readings by predicted_at descending (newest first)
        const sorted = [...result.readings].sort((a, b) => {
            return new Date(b.predicted_at) - new Date(a.predicted_at);
        });

        currentData = {
            readings: sorted,
            deviceId: result.device_id || CONFIG.DEVICE_ID,
            count: result.count || sorted.length,
        };

        // Update device ID in header
        dom.deviceId.textContent = currentData.deviceId.toUpperCase();

        // Render
        renderCards(sorted);
        renderTable(sorted);
        renderCharts(sorted);

        // Update timestamp
        dom.lastUpdated.textContent = new Date().toLocaleString();
        dom.statusDot.className = 'dot';

        if (isFirstLoad) {
            isFirstLoad = false;
        }
    } catch (err) {
        console.error('[refreshDashboard]', err);
        dom.statusDot.className = 'dot paused';
        // Don't blow away existing data on error
    }
}

// ─── AUTO-REFRESH ──────────────────────────────────────────────

function startAutoRefresh() {
    if (refreshTimer) {
        clearInterval(refreshTimer);
    }
    refreshTimer = setInterval(() => {
        refreshDashboard();
    }, CONFIG.REFRESH_INTERVAL_MS);
    dom.refreshLabel.textContent = `Auto-refresh every ${CONFIG.REFRESH_INTERVAL_MS / 1000}s`;
}

function stopAutoRefresh() {
    if (refreshTimer) {
        clearInterval(refreshTimer);
        refreshTimer = null;
        dom.refreshLabel.textContent = 'Auto-refresh stopped';
        dom.statusDot.className = 'dot paused';
    }
}

// ─── INIT ──────────────────────────────────────────────────────

async function init() {
    // Show loading
    dom.tempValue.textContent = '…';
    dom.humidityValue.textContent = '…';
    dom.rainfallValue.textContent = '…';
    dom.advisoryValue.innerHTML = `<span class="no-data-text">Loading…</span>`;
    dom.lastUpdated.textContent = 'Loading…';

    // Initial data load
    await refreshDashboard();

    // Start auto-refresh
    startAutoRefresh();

    // Optional: visibility change — refresh when tab becomes visible
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) {
            // Tab visible again — refresh immediately
            refreshDashboard();
        }
    });

    console.log('🌱 Smart Farm Dashboard initialized.');
    console.log(`📡 Device: ${CONFIG.DEVICE_ID}`);
    console.log(`⏱️  Refresh interval: ${CONFIG.REFRESH_INTERVAL_MS / 1000}s`);
}

// ─── START ─────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', init);
