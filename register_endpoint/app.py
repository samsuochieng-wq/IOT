"""
app.py - register_subscription endpoint
---------------------------------------

Registers browser/device FCM tokens in Firestore.

Deploy on Render:
- Build Command:
    pip install -r requirements.txt

- Start Command:
    gunicorn app:app

Environment Variable:
    FIREBASE_SERVICE_ACCOUNT_JSON
"""

import os
import json

from flask import Flask, request, jsonify
from flask_cors import CORS

import firebase_admin
from firebase_admin import credentials, firestore

app = Flask(__name__)

# Enable CORS so GitHub Pages can call this API
CORS(app)

# Initialize Firebase Admin
service_account_info = json.loads(
    os.environ["FIREBASE_SERVICE_ACCOUNT_JSON"]
)

cred = credentials.Certificate(service_account_info)

firebase_admin.initialize_app(cred)

fs_client = firestore.client()

@app.route("/", methods=["GET"])
def health_check():
    return jsonify({"status": "ok"}), 200

@app.route("/register_subscription", methods=["POST"])
def register_subscription():

    body = request.get_json(silent=True)

    if not body:
        return jsonify({
            "error": "Request body must be valid JSON"
        }), 400

    user_id = body.get("user_id")
    fcm_token = body.get("fcm_token")
    device_id = body.get("device_id")

    missing = [
        field for field in (
            "user_id",
            "fcm_token",
            "device_id"
        )
        if not body.get(field)
    ]

    if missing:
        return jsonify({
            "error": f"Missing required fields: {missing}"
        }), 400

    # Store token under the user document
    user_ref = fs_client.collection("users").document(user_id)

    user_ref.set(
        {
            "fcm_tokens": firestore.ArrayUnion([fcm_token])
        },
        merge=True
    )

    # Register user as subscriber of the device
    sub_ref = (
        fs_client.collection("devices")
        .document(device_id)
        .collection("subscribers")
        .document(user_id)
    )

    sub_ref.set(
        {
            "subscribed_at": firestore.SERVER_TIMESTAMP
        }
    )

    return jsonify(
        {
            "status": "subscribed",
            "user_id": user_id,
            "device_id": device_id
        }
    ), 200

# Handle browser preflight OPTIONS requests
@app.route("/register_subscription", methods=["OPTIONS"])
def register_subscription_options():
    return "", 204

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000))
    )
