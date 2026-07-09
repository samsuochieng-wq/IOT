// Firebase SDK imports
import { initializeApp } from "https://www.gstatic.com/firebasejs/11.9.1/firebase-app.js";
import { getMessaging } from "https://www.gstatic.com/firebasejs/11.9.1/firebase-messaging.js";

// Firebase configuration
const firebaseConfig = {
    apiKey: "AIzaSyBw0eieldINjNpKRhzJwFr4RDxPKXlDhj4",
    authDomain: "iot01-3f1ea.firebaseapp.com",
    databaseURL: "https://iot01-3f1ea-default-rtdb.firebaseio.com",
    projectId: "iot01-3f1ea",
    storageBucket: "iot01-3f1ea.firebasestorage.app",
    messagingSenderId: "660894621070",
    appId: "1:660894621070:web:670de3e001e7205ef498df",
    measurementId: "G-SFGBT9JKYK"
};

// Initialize Firebase
const app = initializeApp(firebaseConfig);

// Initialize Cloud Messaging
const messaging = getMessaging(app);

// Replace with YOUR Web Push Certificate
const vapidKey = "BPhWkuS8U1-EY3oPStGKYYhHf1_QSEAcifE3AyQDf4cgyUrb31hGsp8ZEnggjl24rIDMSdGwc9zfsKsDcImlHx8";

export { app, messaging, vapidKey };
