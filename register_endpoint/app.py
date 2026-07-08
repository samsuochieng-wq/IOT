"""
app.py - register_subscription endpoint
------------------------------------------
A minimal Flask app that replaces the Cloud Function version of
register_subscription, since Cloud Functions now requires the paid Blaze plan.

Deploy this for free on Render.com (Web Service, free tier, no card required):
1. Push this folder to a GitHub repo (or a subfolder of your existing one).
2. On Render.com: New -> Web Service -> connect the repo.
   - Build command:  pip install -r requirements.txt
   - Start command:  gunicorn app:app
3. Add an environment variable FIREBASE_SERVICE_ACCOUNT_JSON with the full
   contents of your Firebase service account key JSON (same one used in the
   GitHub Actions workflow).
4. Render gives you a public URL like https://your-app.onrender.com - that's
   the endpoint your future mobile app calls.

Note: Render's free tier spins the service down after ~15 min of inactivity.
The next request after that has a cold-start delay of some seconds - fine for
an infrequently-called registration endpoint, not fine if you needed
low-latency responses on every call.
"""

import os
import json
from flask import Flask, request, jsonify
import firebase_admin
from firebase_admin import credentials, firestore

app = Flask(__name__)

service_account_info = json.loads(os.environ["FIREBASE_SERVICE_ACCOUNT_JSON"])
cred = credentials.Certificate(service_account_info)
firebase_admin.initialize_app(cred)
fs_client = firestore.client()


@app.route("/register_subscription", methods=["POST"])
def register_subscription():
    body = request.get_json(silent=True)
    if not body:
        return jsonify({"error": "Request body must be JSON"}), 400

    user_id = body.get("user_id")
    fcm_token = body.get("fcm_token")
    device_id = body.get("device_id")

    missing = [k for k in ("user_id", "fcm_token", "device_id") if not body.get(k)]
    if missing:
        return jsonify({"error": f"Missing required fields: {missing}"}), 400

    user_ref = fs_client.collection("users").document(user_id)
    user_ref.set({"fcm_tokens": firestore.ArrayUnion([fcm_token])}, merge=True)

    sub_ref = (fs_client.collection("devices")
               .document(device_id)
               .collection("subscribers")
               .document(user_id))
    sub_ref.set({"subscribed_at": firestore.SERVER_TIMESTAMP})

    return jsonify({"status": "subscribed", "user_id": user_id, "device_id": device_id}), 200


@app.route("/", methods=["GET"])
def health_check():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
