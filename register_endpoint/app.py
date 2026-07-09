"""
app.py
------

Registers browser FCM tokens into Firebase Realtime Database.

No Firestore required.
"""

import os
import json

from flask import Flask, request, jsonify
from flask_cors import CORS

import firebase_admin
from firebase_admin import credentials, db

app = Flask(__name__)

CORS(app)

# -----------------------------
# Firebase Admin Initialization
# -----------------------------

service_account_info = json.loads(
    os.environ["FIREBASE_SERVICE_ACCOUNT_JSON"]
)

cred = credentials.Certificate(service_account_info)

firebase_admin.initialize_app(
    cred,
    {
        "databaseURL": "https://iot01-3f1ea-default-rtdb.firebaseio.com"
    }
)


@app.route("/")
def health():
    return jsonify({"status": "ok"})


@app.route("/register_subscription", methods=["POST"])
def register_subscription():

    body = request.get_json(silent=True)

    if not body:
        return jsonify({"error": "Invalid JSON"}), 400

    user_id = body.get("user_id")
    device_id = body.get("device_id")
    token = body.get("fcm_token")

    if not user_id or not device_id or not token:
        return jsonify({
            "error": "user_id, device_id and fcm_token are required"
        }), 400

    # Store under RTDB
    db.reference(
        f"devices/{device_id}/subscribers/{user_id}"
    ).set({
        "token": token,
        "registered": True
    })

    return jsonify({
        "status": "subscribed"
    })


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000))
    )
