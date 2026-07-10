// Firebase config for IoT project
import { initializeApp } from "https://www.gstatic.com/firebasejs/10.7.1/firebase-app.js";
import { getDatabase } from "https://www.gstatic.com/firebasejs/10.7.1/firebase-database.js";
import { getAuth } from "https://www.gstatic.com/firebasejs/10.7.1/firebase-auth.js";

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

const app = initializeApp(firebaseConfig);
export const db = getDatabase(app);
export const auth = getAuth(app);
