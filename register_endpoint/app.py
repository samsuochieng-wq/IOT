"""
app.py - Smart Farm registration + dashboard backend
-------------------------------------------------------
Two routes:

1. POST /register_subscription
   Writes a subscriber to Realtime Database at:
     /devices/{device_id}/subscribers/{sanitized_email}
   matching the schema your predict_advisory.py already reads from.

2. GET /dashboard-data?device_id=...
   Reads current_advisory + daily_aggregate + a subscriber count from Realtime
   Database and returns them as one JSON payload for the website's live dashboard.
   This exists so the public website never needs direct Firebase read access or
   any embedded secret - it only talks to this backend, which holds the real
   service account credentials server-side.

Deploy on Render (free tier, no card):
    Build command: pip install -r requirements.txt
    Start command: gunicorn app:app
Environment variable required: FIREBASE_SERVICE_ACCOUNT_JSON, FIREBASE_DB_URL
"""

import os
import re
import json
import logging
from datetime import datetime, timezone

from flask import Flask, request, jsonify
from flask_cors import CORS
import firebase_admin
from firebase_admin import credentials, db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("smartfarm_backend")

app = Flask(__name__)
CORS(app)  # allows the public website (different origin) to call this API

service_account_info = json.loads(os.environ["FIREBASE_SERVICE_ACCOUNT_JSON"])
cred = credentials.Certificate(service_account_info)
firebase_admin.initialize_app(cred, {"databaseURL": os.environ["FIREBASE_DB_URL"]})


def sanitize_email_key(email: str) -> str:
    """Turns an email into a Firebase-safe key, e.g. name@x.com -> name_x_com."""
    return re.sub(r"[.@]", "_", email.lower())


@app.route("/register_subscription", methods=["POST"])
def register_subscription():
    body = request.get_json(silent=True)
    if not body:
        return jsonify({"error": "Request body must be JSON"}), 400

    email = (body.get("email") or "").strip().lower()
    device_id = body.get("device_id")

    if not email or not device_id:
        return jsonify({"error": "Missing required fields: email, device_id"}), 400

    email_regex = r"^[^\s@]+@[^\s@]+\.[^\s@]+$"
    if not re.match(email_regex, email):
        return jsonify({"error": "Invalid email address"}), 400

    key = sanitize_email_key(email)

    try:
        db.reference(f"devices/{device_id}/subscribers/{key}").set({
            "email": email,
            "registered": True,
            "registered_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception:
        logger.exception("Failed to write subscriber to Realtime Database")
        return jsonify({"error": "Registration failed - please try again"}), 500

    logger.info(f"Registered subscriber {email} for device {device_id}")
    return jsonify({"status": "registered", "email": email, "device_id": device_id}), 200


@app.route("/dashboard-data", methods=["GET"])
def dashboard_data():
    device_id = request.args.get("device_id")
    if not device_id:
        return jsonify({"error": "Missing required query param: device_id"}), 400

    try:
        current_advisory = db.reference(f"devices/{device_id}/current_advisory").get() or {}
        daily_aggregate = db.reference(f"devices/{device_id}/daily_aggregate").get() or {}
        subscribers = db.reference(f"devices/{device_id}/subscribers").get() or {}
    except Exception:
        logger.exception("Failed to read dashboard data from Realtime Database")
        return jsonify({"error": "Unable to read dashboard data"}), 500

    subscriber_count = sum(
        1 for info in subscribers.values()
        if isinstance(info, dict) and info.get("registered", False)
    )

    response = {
        "device_id": device_id,
        "advisory_label": current_advisory.get("advisory_label", "Normal / No Action"),
        "predicted_at": current_advisory.get("predicted_at"),
        "temp_max": daily_aggregate.get("temp_max"),
        "temp_min": daily_aggregate.get("temp_min"),
        "temp_mean": daily_aggregate.get("temp_mean"),
        "humidity_mean": daily_aggregate.get("humidity_mean"),
        "precipitation_mm": daily_aggregate.get("rain_intensity_avg", 0),
        "subscriber_count": subscriber_count,
    }

    return jsonify(response), 200


@app.route("/history-data", methods=["GET"])
def history_data():
    device_id = request.args.get("device_id")
    if not device_id:
        return jsonify({"error": "Missing required query param: device_id"}), 400

    # Optional limit, e.g. ?limit=100 - defaults to last 200 readings
    try:
        limit = int(request.args.get("limit", 200))
    except ValueError:
        limit = 200

    try:
        # order_by_key + limit_to_last gives the most recent N entries in
        # chronological order, without pulling the entire history every time.
        raw_history = (
            db.reference(f"devices/{device_id}/history")
            .order_by_key()
            .limit_to_last(limit)
            .get()
            or {}
        )
    except Exception:
        logger.exception("Failed to read history from Realtime Database")
        return jsonify({"error": "Unable to read history data"}), 500

    # Firebase push() keys sort chronologically as strings, so this preserves order.
    readings = [
        {
            "predicted_at": entry.get("predicted_at"),
            "advisory_label": entry.get("advisory_label"),
            "temp_mean": entry.get("input", {}).get("temp_mean"),
            "humidity_mean": entry.get("input", {}).get("humidity_mean"),
            "precipitation_mm": entry.get("input", {}).get("precipitation_mm"),
        }
        for entry in raw_history.values()
    ]

    return jsonify({"device_id": device_id, "count": len(readings), "readings": readings}), 200


@app.route("/", methods=["GET"])
def health_check():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
