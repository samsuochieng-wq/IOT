// ==========================================
//  SMART FARM – NOTIFICATION PAGE
// ==========================================

// ─── CHECK IF ALREADY REGISTERED ──────────
(function() {
  const registered = localStorage.getItem('smartfarm_registered');
  if (registered) {
    // Already registered → skip this page and go straight to dashboard
    window.location.href = './dashboard/';  // adjust path if needed
    return;
  }
})();

// ─── CONFIG ───────────────────────────────
const DEVICE_ID = "esp32_001";
const API_BASE = "https://smartfarm-4z48.onrender.com";
const REGISTER_URL = `${API_BASE}/register_subscription`;
const DASHBOARD_URL = `${API_BASE}/dashboard-data`;

// ─── DOM REFS ─────────────────────────────
const registerForm = document.getElementById('registerForm');
const emailInput = document.getElementById('email');
const registerBtn = document.getElementById('registerBtn');
const statusDiv = document.getElementById('status');

// ─── HELPERS ──────────────────────────────
function setStatus(message, kind) {
  statusDiv.textContent = message;
  statusDiv.setAttribute('data-kind', kind);
}

function showSuccessOverlayAndRedirect() {
  const overlay = document.createElement('div');
  overlay.id = 'redirect-overlay';
  overlay.style.cssText = `
    position: fixed;
    top: 0; left: 0; width: 100%; height: 100%;
    background: rgba(0,0,0,0.7);
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    color: white;
    font-family: 'Inter', sans-serif;
    z-index: 9999;
    backdrop-filter: blur(4px);
  `;
  overlay.innerHTML = `
    <div style="font-size: 3.5rem; margin-bottom: 1rem;">✅</div>
    <h2 style="font-weight: 300; margin-bottom: 0.5rem;">Registration Successful</h2>
    <p style="opacity: 0.8; margin-bottom: 1.5rem;">Loading your dashboard...</p>
    <div style="width: 80px; height: 4px; background: #4caf50; border-radius: 4px; animation: pulse-bar 1s ease-in-out infinite;"></div>
    <style>
      @keyframes pulse-bar {
        0% { transform: scaleX(0.2); opacity: 0.5; }
        50% { transform: scaleX(1); opacity: 1; }
        100% { transform: scaleX(0.2); opacity: 0.5; }
      }
    </style>
  `;
  document.body.appendChild(overlay);

  // Wait 1.5 seconds then redirect
  setTimeout(() => {
    window.location.href = './dashboard/';  // or './dashboard/index.html'
  }, 1500);
}

// ─── REGISTRATION SUBMIT ──────────────────
registerForm.addEventListener('submit', async (e) => {
  e.preventDefault();

  const email = emailInput.value.trim();
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

  if (!email) {
    setStatus('Please enter your email address.', 'error');
    return;
  }
  if (!emailRegex.test(email)) {
    setStatus('Please enter a valid email address.', 'error');
    return;
  }

  registerBtn.disabled = true;
  setStatus('Registering...', '');

  try {
    const response = await fetch(REGISTER_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, device_id: DEVICE_ID }),
    });

    const result = await response.json();

    if (!response.ok) {
      setStatus(result.error || 'Registration failed.', 'error');
      return;
    }

    setStatus(`Registered! Advisories will be sent to ${email}.`, 'success');
    emailInput.value = '';

    // ✅ Store flag and redirect
    localStorage.setItem('smartfarm_registered', 'true');
    localStorage.setItem('smartfarm_email', email);

    showSuccessOverlayAndRedirect();

  } catch (err) {
    console.error(err);
    setStatus('Unable to contact the registration server.', 'error');
  } finally {
    registerBtn.disabled = false;
  }
});
