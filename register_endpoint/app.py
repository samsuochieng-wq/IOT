import os
import json
import re
from datetime import datetime, timezone

from flask import Flask, request, jsonify
from flask_cors import CORS

import firebase_admin
from firebase_admin import credentials, db

app = Flask(__name__)

# Allow requests from GitHub Pages
CORS(app)

# -----------------------------
# Firebase Initialization
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

# -----------------------------
# Health Check
# -----------------------------

@app.route("/", methods=["GET"])
def health_check():

    return jsonify({
        "status": "ok"
    })


# -----------------------------
# Register Email Subscriber
# -----------------------------

@app.route("/register_subscription", methods=["POST"])
def register_subscription():

    body = request.get_json(silent=True)

    if not body:

        return jsonify({
            "error": "Request body must be JSON."
        }), 400

    email = body.get("email")
    device_id = body.get("device_id")

    if not email or not device_id:

        return jsonify({
            "error": "Both email and device_id are required."
        }), 400

    email = email.strip().lower()

    # Basic email validation
    email_pattern = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"

    if not re.match(email_pattern, email):

        return jsonify({
            "error": "Invalid email address."
        }), 400

    # Firebase keys cannot contain . # $ [ ] /
    subscriber_key = (
        email.replace(".", "_")
             .replace("@", "_")
    )

    subscriber_ref = db.reference(
        f"/devices/{device_id}/subscribers/{subscriber_key}"
    )

    subscriber_ref.set({

        "email": email,

        "registered": True,

        "registered_at": datetime.now(
            timezone.utc
        ).isoformat()

    })

    return jsonify({

        "status": "subscribed",

        "email": email

    }), 200


# -----------------------------
# Main
# -----------------------------

if __name__ == "__main__":

    app.run(

        host="0.0.0.0",

        port=int(
            os.environ.get("PORT", 5000)
        )

    )