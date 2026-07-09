import { messaging, vapidKey } from "./firebase-config.js";

import {
    getToken,
    onMessage
} from "https://www.gstatic.com/firebasejs/11.9.1/firebase-messaging.js";

// ---------------- CONFIG ----------------

const DEVICE_ID = "esp32_001";
const USER_ID = "bob_macnill";

const REGISTER_ENDPOINT =
    "https://smartfarm-4z48.onrender.com/register_subscription";

// ----------------------------------------

const statusDiv = document.getElementById("status");
const enableBtn = document.getElementById("enableBtn");

enableBtn.addEventListener("click", async () => {

    statusDiv.innerHTML = "Requesting notification permission...";

    try {

        // Request browser notification permission
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
            statusDiv.innerHTML = "❌ Failed to generate FCM token.";
            return;
        }

        console.log("FCM Token:", token);

        statusDiv.innerHTML = "Registering with Smart Farm server...";

        // Send the token to the Render backend
        const response = await fetch(REGISTER_ENDPOINT, {

            method: "POST",

            headers: {
                "Content-Type": "application/json"
            },

            body: JSON.stringify({

                user_id: USER_ID,
                device_id: DEVICE_ID,
                fcm_token: token

            })

        });

        const result = await response.json();

        console.log("Server Response:", result);

        if (!response.ok) {
            throw new Error(result.error || "Registration failed");
        }

        statusDiv.innerHTML =
            "✅ Browser successfully subscribed to Smart Farm notifications!";

    }
    catch (err) {

        console.error(err);

        statusDiv.innerHTML =
            "❌ Error: " + err.message;

    }

});

// Receive notifications while page is open
onMessage(messaging, (payload) => {

    console.log("Notification received:", payload);

    if (payload.notification) {

        alert(
            payload.notification.title +
            "\n\n" +
            payload.notification.body
        );

    }

});
