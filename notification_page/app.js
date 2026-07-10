// ------------------------------------------
// Smart Farm Advisory - Dashboard + Registration
// ------------------------------------------

const DEVICE_ID = "esp32_001";
const API_BASE = "https://smartfarm-4z48.onrender.com"; // your Render backend
const REGISTER_URL = `${API_BASE}/register_subscription`;
const DASHBOARD_URL = `${API_BASE}/dashboard-data`;
const REFRESH_INTERVAL_MS = 30000;

// ---------- Dark mode ----------

const themeToggle = document.getElementById("themeToggle");
const themeIcon = document.getElementById("themeIcon");

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  themeIcon.textContent = theme === "dark" ? "☀️" : "🌙";
  localStorage.setItem("smartfarm-theme", theme);
}

(function initTheme() {
  const saved = localStorage.getItem("smartfarm-theme");
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  applyTheme(saved || (prefersDark ? "dark" : "light"));
})();

themeToggle.addEventListener("click", () => {
  const current = document.documentElement.getAttribute("data-theme");
  applyTheme(current === "dark" ? "light" : "dark");
});

// ---------- Advisory label -> visual state + plain-language explanation ----------

const ADVISORY_META = {
  "Normal / No Action": {
    state: "normal",
    explanation: "Conditions are stable. No intervention needed right now.",
  },
  "Irrigate Immediately": {
    state: "irrigate",
    explanation: "Hot and dry with no rainfall detected. Irrigation is recommended now to prevent crop water stress.",
  },
  "Delay Fertilizer": {
    state: "rain",
    explanation: "Heavy rainfall detected. Holding off on fertilizer avoids runoff and wasted product.",
  },
  "High Fungal Risk": {
    state: "fungal",
    explanation: "High humidity combined with warm temperatures favors fungal growth. Consider preventive treatment and improve airflow.",
  },
};

function formatLastUpdate(isoString) {
  if (!isoString) return "Last update: \u2014";
  const date = new Date(isoString);
  if (isNaN(date.getTime())) return "Last update: \u2014";
  return "Last update: " + date.toLocaleString(undefined, {
    hour: "numeric",
    minute: "2-digit",
    month: "short",
    day: "numeric",
  });
}

function crossfadeText(el, newText) {
  el.style.opacity = 0;
  setTimeout(() => {
    el.textContent = newText;
    el.style.opacity = 1;
  }, 150);
}

// ---------- Dashboard polling ----------

const valTemp = document.getElementById("valTemp");
const valHumidity = document.getElementById("valHumidity");
const valRain = document.getElementById("valRain");
const advisoryCard = document.getElementById("advisoryCard");
const advisoryLabel = document.getElementById("advisoryLabel");
const advisoryExplanation = document.getElementById("advisoryExplanation");
const lastUpdateEl = document.getElementById("lastUpdate");
const subscriberCountEl = document.getElementById("subscriberCount");

async function refreshDashboard() {
  try {
    const response = await fetch(`${DASHBOARD_URL}?device_id=${DEVICE_ID}`);
    if (!response.ok) throw new Error(`Server returned ${response.status}`);
    const data = await response.json();

    const tempText = (data.temp_mean ?? "--") + "\u00b0C";
    const humidityText = (data.humidity_mean ?? "--") + "%";
    const rainText = data.precipitation_mm > 0 ? "Rain" : "No Rain";

    crossfadeText(valTemp, tempText);
    crossfadeText(valHumidity, humidityText);
    crossfadeText(valRain, rainText);

    const label = data.advisory_label || "Normal / No Action";
    const meta = ADVISORY_META[label] || ADVISORY_META["Normal / No Action"];

    advisoryCard.setAttribute("data-state", meta.state);
    crossfadeText(advisoryLabel, label);
    crossfadeText(advisoryExplanation, meta.explanation);

    lastUpdateEl.textContent = formatLastUpdate(data.predicted_at);
    subscriberCountEl.textContent = `${data.subscriber_count ?? 0} farmers subscribed`;

  } catch (err) {
    console.error("Dashboard refresh failed:", err);
    advisoryExplanation.textContent = "Unable to reach the dashboard server. Retrying shortly...";
  }
}

refreshDashboard();
setInterval(refreshDashboard, REFRESH_INTERVAL_MS);

// ---------- Registration ----------

const registerForm = document.getElementById("registerForm");
const emailInput = document.getElementById("email");
const registerBtn = document.getElementById("registerBtn");
const statusDiv = document.getElementById("status");

function setStatus(message, kind) {
  statusDiv.textContent = message;
  statusDiv.setAttribute("data-kind", kind);
}

registerForm.addEventListener("submit", async (e) => {
  e.preventDefault();

  const email = emailInput.value.trim();
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

  if (!email) {
    setStatus("Please enter your email address.", "error");
    return;
  }
  if (!emailRegex.test(email)) {
    setStatus("Please enter a valid email address.", "error");
    return;
  }

  registerBtn.disabled = true;
  setStatus("Registering...", "");

  try {
    const response = await fetch(REGISTER_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, device_id: DEVICE_ID }),
    });

    const result = await response.json();

    if (!response.ok) {
      setStatus(result.error || "Registration failed.", "error");
      return;
    }

    setStatus(`Registered! Advisories will be sent to ${email}.`, "success");
    emailInput.value = "";
    refreshDashboard(); // subscriber count just changed

  } catch (err) {
    console.error(err);
    setStatus("Unable to contact the registration server.", "error");
  } finally {
    registerBtn.disabled = false;
  }
});
