// ==========================================
//  SMART FARM – NOTIFICATION PAGE (Google Auth)
// ==========================================

import { auth, db } from './firebase-config.js';
import {
  signInWithPopup,
  GoogleAuthProvider,
  signInWithEmailAndPassword,
  onAuthStateChanged,
  setPersistence,
  browserLocalPersistence,
} from 'https://www.gstatic.com/firebasejs/10.7.1/firebase-auth.js';
import { ref, set } from 'https://www.gstatic.com/firebasejs/10.7.1/firebase-database.js';

// ─── CONFIG ───────────────────────────────
const DEVICE_ID = 'esp32_001';

// ─── DOM REFS ─────────────────────────────
const googleBtn = document.getElementById('googleBtn');
const emailForm = document.getElementById('emailForm');
const emailInput = document.getElementById('emailInput');
const emailSignInBtn = document.getElementById('emailSignInBtn');
const statusDiv = document.getElementById('status');

// ─── HELPERS ──────────────────────────────
function setStatus(msg, kind) {
  statusDiv.textContent = msg;
  statusDiv.setAttribute('data-kind', kind);
}

function showSuccessOverlayAndRedirect() {
  const overlay = document.createElement('div');
  overlay.style.cssText = `
    position: fixed; top:0; left:0; width:100%; height:100%;
    background: rgba(0,0,0,0.7);
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    color: white; font-family: 'Inter', sans-serif; z-index: 9999;
    backdrop-filter: blur(4px);
  `;
  overlay.innerHTML = `
    <div style="font-size:3.5rem; margin-bottom:1rem;">✅</div>
    <h2 style="font-weight:300; margin-bottom:0.5rem;">Welcome!</h2>
    <p style="opacity:0.8; margin-bottom:1.5rem;">Loading your dashboard...</p>
    <div style="width:80px; height:4px; background:#4caf50; border-radius:4px; animation:pulse-bar 1s ease-in-out infinite;"></div>
    <style>
      @keyframes pulse-bar {
        0% { transform:scaleX(0.2); opacity:0.5; }
        50% { transform:scaleX(1); opacity:1; }
        100% { transform:scaleX(0.2); opacity:0.5; }
      }
    </style>
  `;
  document.body.appendChild(overlay);

  setTimeout(() => {
    window.location.href = './dashboard/';
  }, 1500);
}

async function saveSubscriber(user) {
  const email = user.email;
  const uid = user.uid;
  const displayName = user.displayName || email.split('@')[0];

  const subscriberRef = ref(db, `devices/${DEVICE_ID}/subscribers/${uid.replace(/[.#$]/g, '_')}`);
  try {
    await set(subscriberRef, {
      email: email,
      name: displayName,
      registered_at: new Date().toISOString(),
      provider: 'google.com',
    });
  } catch (err) {
    console.error('Error saving subscriber:', err);
  }
}

function handleSignInSuccess(user) {
  saveSubscriber(user);
  localStorage.setItem('smartfarm_registered', 'true');
  localStorage.setItem('smartfarm_email', user.email);
  localStorage.setItem('smartfarm_name', user.displayName || user.email);
  showSuccessOverlayAndRedirect();
}

// ─── GOOGLE SIGN-IN ──────────────────────
googleBtn.addEventListener('click', async () => {
  const provider = new GoogleAuthProvider();
  try {
    setStatus('Signing in...', '');
    const result = await signInWithPopup(auth, provider);
    handleSignInSuccess(result.user);
  } catch (error) {
    console.error(error);
    setStatus(error.message || 'Sign-in failed.', 'error');
  }
});

// ─── EMAIL FALLBACK ──────────────────────
emailForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const email = emailInput.value.trim();
  const password = prompt('Enter a password (minimum 6 characters) to create your account:');
  if (!password || password.length < 6) {
    setStatus('Password must be at least 6 characters.', 'error');
    return;
  }

  emailSignInBtn.disabled = true;
  setStatus('Creating account...', '');

  try {
    const { createUserWithEmailAndPassword } = await import('https://www.gstatic.com/firebasejs/10.7.1/firebase-auth.js');
    const userCredential = await createUserWithEmailAndPassword(auth, email, password);
    handleSignInSuccess(userCredential.user);
  } catch (error) {
    console.error(error);
    setStatus(error.message || 'Email sign-in failed.', 'error');
  } finally {
    emailSignInBtn.disabled = false;
  }
});

// ─── AUTO-REDIRECT IF ALREADY SIGNED IN ──
setPersistence(auth, browserLocalPersistence).then(() => {
  onAuthStateChanged(auth, (user) => {
    if (user) {
      window.location.href = './dashboard/';
    }
  });
});
