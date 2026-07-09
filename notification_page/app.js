const statusBox = document.getElementById("status");
const enableButton = document.getElementById("enable-notifications");

function setStatus(message) {
  statusBox.textContent = message;
}

if (!window.firebaseConfig) {
  setStatus("Firebase config is missing. Update firebase-config.js first.");
} else {
  firebase.initializeApp(window.firebaseConfig);
  const messaging = firebase.messaging();

  enableButton.addEventListener("click", async () => {
    try {
      if (!("Notification" in window)) {
        setStatus("This browser does not support notifications.");
        return;
      }

      const permission = await Notification.requestPermission();
      setStatus(`Notification permission: ${permission}`);

      if (permission === "granted") {
        const registration = await navigator.serviceWorker.register("./firebase-messaging-sw.js");
        const token = await messaging.getToken({ vapidKey: "YOUR_VAPID_PUBLIC_KEY", serviceWorkerRegistration: registration });
        setStatus(`Notification permission granted. FCM token: ${token}`);
      }
    } catch (error) {
      console.error(error);
      setStatus(`Error: ${error.message}`);
    }
  });

  messaging.onMessage((payload) => {
    console.log("Message received", payload);
    setStatus(`Message received: ${JSON.stringify(payload, null, 2)}`);
  });
}
