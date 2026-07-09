importScripts("https://www.gstatic.com/firebasejs/10.12.2/firebase-app-compat.js");
importScripts("https://www.gstatic.com/firebasejs/10.12.2/firebase-messaging-compat.js");

self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

const firebaseConfig = {
  apiKey: "YOUR_API_KEY",
  authDomain: "iot01-3f1ea.firebaseapp.com",
  projectId: "iot01-3f1ea",
  databaseURL: "https://iot01-3f1ea-default-rtdb.firebaseio.com",
  storageBucket: "iot01-3f1ea.appspot.com",
  messagingSenderId: "YOUR_MESSAGING_SENDER_ID",
  appId: "YOUR_APP_ID"
};

firebase.initializeApp(firebaseConfig);
const messaging = firebase.messaging();

messaging.onBackgroundMessage((payload) => {
  const notificationTitle = payload.notification?.title || "Farm Advisory Alert";
  const notificationOptions = {
    body: payload.notification?.body || "You have a new advisory update.",
    icon: "/notification_page/icon.png"
  };

  return self.registration.showNotification(notificationTitle, notificationOptions);
});
