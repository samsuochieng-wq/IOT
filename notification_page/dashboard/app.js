// ==========================================
//  SMART FARM – DASHBOARD (Full)
// ==========================================

// ─── CHECK IF REGISTERED ──────────────────
(function() {
  const registered = localStorage.getItem('smartfarm_registered');
  if (!registered) {
    window.location.href = '../';
    return;
  }
})();

// ─── USER GREETING & SIGN OUT ──────────────
const userGreeting = document.getElementById('userGreeting');
const signOutBtn = document.getElementById('signOutBtn');
const name = localStorage.getItem('smartfarm_name') || 'Farmer';
if (userGreeting) userGreeting.textContent = `Hello, ${name} 👋`;
if (signOutBtn) {
  signOutBtn.addEventListener('click', () => {
    localStorage.removeItem('smartfarm_registered');
    localStorage.removeItem('smartfarm_email');
    localStorage.removeItem('smartfarm_name');
    // Attempt Firebase sign-out if config exists
    import('./firebase-config.js').then(({ auth }) => {
      auth.signOut();
    }).catch(() => {});
    window.location.href = '../';
  });
}

// ─── CONFIG ──────────────────────────────────
const CONFIG = {
    API_BASE: 'https://smartfarm-4z48.onrender.com',
    DEVICE_ID: 'esp32_001',
    REFRESH_INTERVAL_MS: 30000,
    MAX_ADVISORIES: 50,
};

let chartInstances = { temp: null, humidity: null, rainfall: null };
let currentData = { readings: [], deviceId: '', count: 0 };
let refreshTimer = null;
let isFirstLoad = true;

// ─── DOM REFS ──────────────────────────────
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

// ─── HELPERS ──────────────────────────────────
function getReadingValue(reading, keys) {
    if (!reading) return undefined;
    // Try root level first
    for (const key of keys) {
        if (reading[key] !== undefined && reading[key] !== null) return reading[key];
    }
    // Try inside 'input' object
    const input = reading.input || {};
    for (const key of keys) {
        if (input[key] !== undefined && input[key] !== null) return input[key];
    }
    return undefined;
}

function formatDateShort(dateStr) {
    if (!dateStr) return '—';
    try {
        const d = new Date(dateStr);
        if (isNaN(d.getTime())) return dateStr;
        return d.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    } catch (_) { return dateStr; }
}

function getAdvisoryClass(label) {
    if (!label) return 'info';
    const l = label.toLowerCase();
    if (l.includes('optimal') || l.includes('excellent') || l.includes('good')) return 'optimal';
    if (l.includes('critical') || l.includes('severe') || l.includes('danger') || l.includes('high risk')) return 'critical';
    if (l.includes('warning') || l.includes('caution') || l.includes('moderate')) return 'warning';
    if (l.includes('monitor') || l.includes('watch') || l.includes('check')) return 'monitor';
    return 'info';
}

function truncateAdvisory(label, maxLen = 60) {
    if (!label) return '—';
    return label.length > maxLen ? label.slice(0, maxLen) + '…' : label;
}

// ─── API ──────────────────────────────────────
async function fetchHistoryData() {
    const url = `${CONFIG.API_BASE}/history-data?device_id=${encodeURIComponent(CONFIG.DEVICE_ID)}`;
    try {
        const resp = await fetch(url);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        return await resp.json();
    } catch (err) {
        console.warn('[fetchHistoryData]', err.message);
        return null;
    }
}

// ─── RENDER CARDS (INCLUDES WEATHER) ────────
function renderCards(readings) {
    if (!readings || readings.length === 0) {
        dom.tempValue.textContent = '--';
        dom.humidityValue.textContent = '--';
        dom.rainfallValue.textContent = '--';
        dom.advisoryValue.innerHTML = `<span class="no-data-text">No data</span>`;
        document.getElementById('forecast-note').textContent = '';
        document.getElementById('rain-prob-value').textContent = '--';
        document.getElementById('wind-value').textContent = '--';
        document.getElementById('pressure-value').textContent = '--';
        document.getElementById('weather-desc-value').textContent = '--';
        document.getElementById('weather-cards').style.display = 'none';
        return;
    }

    const latest = readings[0];

    // Temperature
    const temp = getReadingValue(latest, ['temp_mean', 'temperature', 'temp', 't']);
    dom.tempValue.textContent = temp !== undefined && temp !== null ? Number(temp).toFixed(1) : '--';

    // Humidity
    const hum = getReadingValue(latest, ['humidity_mean', 'humidity', 'hum', 'h']);
    dom.humidityValue.textContent = hum !== undefined && hum !== null ? Number(hum).toFixed(0) : '--';

    // Rainfall
    const rain = getReadingValue(latest, ['precipitation_mm', 'precipitation', 'rain', 'rainfall', 'r']);
    dom.rainfallValue.textContent = rain !== undefined && rain !== null ? Number(rain).toFixed(1) : '--';

    // Advisory
    const label = latest.advisory_label || 'No advisory';
    const cls = getAdvisoryClass(label);
    dom.advisoryValue.innerHTML = `
        <span class="advisory-badge ${cls}">${truncateAdvisory(label, 50)}</span>
    `;

    // Forecast note
    const forecastNote = latest.forecast_note || '';
    document.getElementById('forecast-note').textContent = forecastNote;

    // Weather forecast (root level)
    const weather = latest.weather_forecast || {};
    const rainProb = weather.rain_prob !== undefined ? weather.rain_prob : '--';
    const windTomorrow = weather.wind_speed !== undefined ? weather.wind_speed : '--';
    const pressureTomorrow = weather.pressure !== undefined ? weather.pressure : '--';
    const desc = weather.description || '--';

    document.getElementById('rain-prob-value').textContent = rainProb !== '--' ? rainProb : '--';
    document.getElementById('wind-value').textContent = windTomorrow !== '--' ? Number(windTomorrow).toFixed(1) : '--';
    document.getElementById('pressure-value').textContent = pressureTomorrow !== '--' ? Number(pressureTomorrow).toFixed(0) : '--';
    document.getElementById('weather-desc-value').textContent = desc;

    // Show/hide weather row
    const weatherRow = document.getElementById('weather-cards');
    if (weather.rain_prob === undefined && !weather.description && !weather.wind_speed) {
        weatherRow.style.display = 'none';
    } else {
        weatherRow.style.display = 'grid';
    }
}

// ─── RENDER TABLE ────────────────────────────
function renderTable(readings) {
    const tbody = dom.advisoryBody;
    const countEl = dom.advisoryCount;
    if (!readings || readings.length === 0) {
        tbody.innerHTML = `<tr class="empty-row"><td colspan="2">No advisory data available</td></tr>`;
        countEl.textContent = '0 advisories';
        return;
    }
    const rows = readings.slice(0, CONFIG.MAX_ADVISORIES);
    countEl.textContent = `${rows.length} advisory${rows.length !== 1 ? 'ies' : ''}`;
    let html = '';
    for (const r of rows) {
        const date = formatDateShort(r.predicted_at);
        const label = r.advisory_label || '—';
        const cls = getAdvisoryClass(label);
        html += `<tr><td class="date-cell">${date}</td><td><span class="advisory-tag ${cls}">${truncateAdvisory(label, 70)}</span></td></tr>`;
    }
    tbody.innerHTML = html;
}

// ─── RENDER CHARTS ────────────────────────────
function updateOrCreateChart(canvasId, label, color, dataPoints, unit = '') {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return null;
    const sorted = [...dataPoints].reverse();
    const labels = sorted.map((d) => {
        const dt = new Date(d.predicted_at);
        return dt.toLocaleString('en-US', { hour: '2-digit', minute: '2-digit', month: 'short', day: 'numeric' });
    });
    let values;
    switch (canvasId) {
        case 'temp-chart':
            values = sorted.map((d) => getReadingValue(d, ['temp_mean', 'temperature', 'temp', 't']));
            break;
        case 'humidity-chart':
            values = sorted.map((d) => getReadingValue(d, ['humidity_mean', 'humidity', 'hum', 'h']));
            break;
        case 'rainfall-chart':
            values = sorted.map((d) => getReadingValue(d, ['precipitation_mm', 'precipitation', 'rain', 'rainfall', 'r']));
            break;
        default: values = [];
    }
    if (chartInstances[canvasId]) {
        const chart = chartInstances[canvasId];
        chart.data.labels = labels;
        chart.data.datasets[0].data = values;
        chart.update('none');
        return chart;
    }
    const ctx = canvas.getContext('2d');
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
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: function(ctx) {
                            let val = ctx.parsed.y;
                            if (val === null || val === undefined) return 'No data';
                            return `${Number(val).toFixed(1)} ${unit}`.trim();
                        }
                    }
                }
            },
            scales: {
                x: {
                    grid: { display: false },
                    ticks: { maxTicksLimit: 8, font: { size: 9 }, color: '#8a9a8a' }
                },
                y: {
                    grid: { color: 'rgba(0,0,0,0.05)' },
                    ticks: { font: { size: 9 }, color: '#8a9a8a', callback: (v) => Number(v).toFixed(0) },
                    beginAtZero: canvasId === 'rainfall-chart' ? true : undefined
                }
            },
            interaction: { intersect: false, mode: 'index' }
        }
    });
    chartInstances[canvasId] = newChart;
    return newChart;
}

function renderCharts(readings) {
    const data = readings || [];
    const colors = { temp: '#e65100', humidity: '#0d47a1', rainfall: '#00695c' };
    updateOrCreateChart('temp-chart', 'Temperature', colors.temp, data, '°C');
    updateOrCreateChart('humidity-chart', 'Humidity', colors.humidity, data, '%');
    updateOrCreateChart('rainfall-chart', 'Rainfall', colors.rainfall, data, 'mm');
}

// ─── MAIN UPDATE ──────────────────────────────
async function refreshDashboard() {
    try {
        if (isFirstLoad) {
            dom.tempValue.textContent = '…';
            dom.humidityValue.textContent = '…';
            dom.rainfallValue.textContent = '…';
            dom.advisoryValue.innerHTML = `<span class="no-data-text">Loading…</span>`;
        }
        const result = await fetchHistoryData();
        if (!result || !result.readings || result.readings.length === 0) {
            currentData = { readings: [], deviceId: result?.device_id || CONFIG.DEVICE_ID, count: 0 };
            renderCards([]);
            renderTable([]);
            renderCharts([]);
            dom.lastUpdated.textContent = new Date().toLocaleString();
            dom.statusDot.className = 'dot paused';
            if (isFirstLoad) dom.advisoryValue.innerHTML = `<span class="no-data-text">No data available</span>`;
            isFirstLoad = false;
            return;
        }
        const sorted = [...result.readings].sort((a, b) => new Date(b.predicted_at) - new Date(a.predicted_at));
        currentData = { readings: sorted, deviceId: result.device_id || CONFIG.DEVICE_ID, count: result.count || sorted.length };
        dom.deviceId.textContent = currentData.deviceId.toUpperCase();
        renderCards(sorted);
        renderTable(sorted);
        renderCharts(sorted);
        dom.lastUpdated.textContent = new Date().toLocaleString();
        dom.statusDot.className = 'dot';
        if (isFirstLoad) isFirstLoad = false;
    } catch (err) {
        console.error('[refreshDashboard]', err);
        dom.statusDot.className = 'dot paused';
    }
}

// ─── AUTO-REFRESH ────────────────────────────
function startAutoRefresh() {
    if (refreshTimer) clearInterval(refreshTimer);
    refreshTimer = setInterval(refreshDashboard, CONFIG.REFRESH_INTERVAL_MS);
    dom.refreshLabel.textContent = `Auto-refresh every ${CONFIG.REFRESH_INTERVAL_MS / 1000}s`;
}

// ─── INIT ─────────────────────────────────────
async function init() {
    dom.tempValue.textContent = '…';
    dom.humidityValue.textContent = '…';
    dom.rainfallValue.textContent = '…';
    dom.advisoryValue.innerHTML = `<span class="no-data-text">Loading…</span>`;
    dom.lastUpdated.textContent = 'Loading…';
    await refreshDashboard();
    startAutoRefresh();
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) refreshDashboard();
    });
    console.log('🌱 Smart Farm Dashboard initialized.');
    console.log(`📡 Device: ${CONFIG.DEVICE_ID}`);
}

document.addEventListener('DOMContentLoaded', init);
