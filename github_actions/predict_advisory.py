"""
predict_advisory.py
--------------------

GitHub Actions script for Smart Farm AI.

Pipeline:

ESP32
   ↓
Realtime Database (daily_aggregate)
   ↓
GitHub Actions
   ↓
Machine Learning Model
   ↓
Realtime Database (current_advisory)
   ↓
FCM Push Notification
   ↓
Browser

No Firestore required.
"""

import os
import sys
import json
import joblib
import pandas as pd
import firebase_admin

from firebase_admin import (
    credentials,
    db,
    messaging
)

MODEL_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "models",
    "farm_advisory_model.joblib"
)

FIREBASE_DB_URL = os.environ["FIREBASE_DB_URL"]
DEVICE_ID = os.environ["DEVICE_ID"]

NOTIFY_ON_LABELS = {
    "High Fungal Risk",
    "Irrigate Immediately",
    "Delay Fertilizer"
}

# ----------------------------------------------------
# Initialize Firebase
# ----------------------------------------------------

def init_firebase():

    service_account_info = json.loads(
        os.environ["FIREBASE_SERVICE_ACCOUNT_JSON"]
    )

    cred = credentials.Certificate(service_account_info)

    firebase_admin.initialize_app(
        cred,
        {
            "databaseURL": FIREBASE_DB_URL
        }
    )

# ----------------------------------------------------
# Load ML Model
# ----------------------------------------------------

def load_model_bundle():

    if not os.path.exists(MODEL_PATH):

        print("Model not found:")
        print(MODEL_PATH)

        sys.exit(1)

    return joblib.load(MODEL_PATH)

# ----------------------------------------------------
# Read latest aggregate
# ----------------------------------------------------

def fetch_latest_reading(device_id):

    reading = db.reference(
        f"/devices/{device_id}/daily_aggregate"
    ).get()

    if not reading:

        print("No daily aggregate available.")

        sys.exit(0)

    return reading

# ----------------------------------------------------
# Read FCM Tokens
# ----------------------------------------------------

def get_subscribed_tokens(device_id):

    subscribers = db.reference(
        f"/devices/{device_id}/subscribers"
    ).get()

    if not subscribers:

        print("No subscribers registered.")

        return []

    tokens = []

    for token, info in subscribers.items():

        if isinstance(info, dict) and info.get("enabled", False):

            tokens.append(token)

    print(f"Found {len(tokens)} subscriber(s).")

    return tokens

# ----------------------------------------------------
# Send Notification
# ----------------------------------------------------

def send_notifications(device_id, advisory_label, tokens):

    if len(tokens) == 0:

        print("Nothing to notify.")

        return

    body_map = {

        "High Fungal Risk":
            "Conditions favour fungal disease. Consider preventive spraying.",

        "Irrigate Immediately":
            "Hot and dry conditions detected. Irrigation is recommended.",

        "Delay Fertilizer":
            "Heavy rain detected. Delay fertilizer application."

    }

    body = body_map.get(
        advisory_label,
        f"New farm advisory: {advisory_label}"
    )

    message = messaging.MulticastMessage(

        notification=messaging.Notification(

            title="🌱 Smart Farm Alert",

            body=body

        ),

        data={

            "device_id": device_id,

            "advisory_label": advisory_label

        },

        tokens=tokens

    )

    response = messaging.send_each_for_multicast(
        message
    )

    print(
        f"Notifications sent:"
        f" {response.success_count} success,"
        f" {response.failure_count} failed."
    )

# ----------------------------------------------------
# Main
# ----------------------------------------------------

def main():

    init_firebase()

    bundle = load_model_bundle()

    model = bundle["model"]

    label_encoder = bundle["label_encoder"]

    feature_order = bundle["feature_order"]

    reading = fetch_latest_reading(
        DEVICE_ID
    )

    live_reading = {

        "temp_max":
            reading.get("temp_max"),

        "temp_min":
            reading.get("temp_min"),

        "temp_mean":
            reading.get("temp_mean"),

        "humidity_mean":
            reading.get("humidity_mean"),

        "precipitation_mm":
            reading.get(
                "rain_intensity_avg",
                0.0
            )

    }

    missing = [

        key

        for key, value in live_reading.items()

        if value is None

    ]

    if missing:

        print("Missing sensor values:")

        print(missing)

        sys.exit(1)

    live_df = pd.DataFrame(
        [live_reading]
    )[feature_order]

    prediction = model.predict(
        live_df
    )

    advisory_label = label_encoder.inverse_transform(
        prediction
    )[0]

    print()

    print("Predicted Advisory:")

    print(advisory_label)

    print()

    db.reference(

        f"/devices/{DEVICE_ID}/current_advisory"

    ).set({

        "device_id": DEVICE_ID,

        "advisory_label": advisory_label,

        "input": live_reading

    })

    print("Realtime Database updated.")

    if advisory_label in NOTIFY_ON_LABELS:

        tokens = get_subscribed_tokens(
            DEVICE_ID
        )

        send_notifications(

            DEVICE_ID,

            advisory_label,

            tokens

        )

    else:

        print(
            "Notification not required."
        )

if __name__ == "__main__":

    main()
