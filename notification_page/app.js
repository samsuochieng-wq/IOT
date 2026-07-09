import { messaging, vapidKey, app } from "./firebase-config.js";

import {
    getToken,
    onMessage
} from "https://www.gstatic.com/firebasejs/11.9.1/firebase-messaging.js";

import {
    getDatabase,
    ref,
    set
} from "https://www.gstatic.com/firebasejs/11.9.1/firebase-database.js";

const DEVICE_ID = "esp32_001";

const statusDiv = document.getElementById("status");
const enableBtn = document.getElementById("enableBtn");

const db = getDatabase(app);

enableBtn.addEventListener("click", async () => {

    statusDiv.innerHTML = "Requesting notification permission...";

    try {

        // Ask browser permission
        const permission = await Notification.requestPermission();

        if (permission !== "granted") {
            statusDiv.innerHTML = "❌ Notification permission denied.";
            return;
        }

        statusDiv.innerHTML = "Registering service worker...";

        // Register service worker
        const registration = await navigator.serviceWorker.register(
            "./firebase-messaging-sw.js"
        );

        statusDiv.innerHTML = "Generating FCM token...";

        // Generate FCM token
        const token = await getToken(messaging, {
            vapidKey: vapidKey,
            serviceWorkerRegistration: registration
        });

        if (!token) {
            statusDiv.innerHTML = "❌ Failed to generate token.";
            return;
        }

        console.log("FCM Token:", token);

        // Save token to Realtime Database
        await set(
            ref(db, `devices/${DEVICE_ID}/subscribers/${token}`),
            {
                token: token,
                browser: navigator.userAgent,
                platform: navigator.platform,
                enabled: true,
                registered_at: new Date().toISOString()
            }
        );

        statusDiv.innerHTML =
            "✅ Browser successfully registered for notifications!";

    }
    catch (err) {

        console.error(err);

        statusDiv.innerHTML =
            "❌ Error: " + err.message;

    }

});

// Receive notifications while page is open
onMessage(messaging, (payload) => {

    console.log("Message received:", payload);

    alert(
        payload.notification.title +
        "\n\n" +
        payload.notification.body
    );

});
