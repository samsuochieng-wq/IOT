// Firebase Service Worker

importScripts("https://www.gstatic.com/firebasejs/11.9.1/firebase-app-compat.js");
importScripts("https://www.gstatic.com/firebasejs/11.9.1/firebase-messaging-compat.js");

firebase.initializeApp({
    apiKey: "AIzaSyBw0eieldINjNpKRhzJwFr4RDxPKXlDhj4",
    authDomain: "iot01-3f1ea.firebaseapp.com",
    databaseURL: "https://iot01-3f1ea-default-rtdb.firebaseio.com",
    projectId: "iot01-3f1ea",
    storageBucket: "iot01-3f1ea.firebasestorage.app",
    messagingSenderId: "660894621070",
    appId: "1:660894621070:web:670de3e001e7205ef498df"
});

const messaging = firebase.messaging();

messaging.onBackgroundMessage((payload) => {

    console.log("Background Message:", payload);

    const notificationTitle =
        payload.notification?.title || "Smart Farm";

    const notificationOptions = {
        body: payload.notification?.body || "",
        icon: "https://cdn-icons-png.flaticon.com/512/2909/2909762.png"
    };

    self.registration.showNotification(
        notificationTitle,
        notificationOptions
    );

});
