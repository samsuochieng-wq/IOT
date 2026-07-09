import os
import sys
import json
import joblib
import pandas as pd

import firebase_admin
from firebase_admin import credentials, db, messaging

# ---------------------------------------------------
# Configuration
# ---------------------------------------------------

MODEL_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "models",
    "farm_advisory_model.joblib"
)

FIREBASE_DB_URL = os.environ["FIREBASE_DB_URL"]
DEVICE_ID = os.environ["DEVICE_ID"]

# During testing we notify on every advisory.
# Later you can change this back to only urgent labels.
NOTIFY_ON_ALL = True

NOTIFY_ON_LABELS = {
    "High Fungal Risk",
    "Irrigate Immediately",
    "Delay Fertilizer"
}

# ---------------------------------------------------
# Firebase
# ---------------------------------------------------

def init_firebase():

    service_account = json.loads(
        os.environ["FIREBASE_SERVICE_ACCOUNT_JSON"]
    )

    cred = credentials.Certificate(service_account)

    firebase_admin.initialize_app(
        cred,
        {
            "databaseURL": FIREBASE_DB_URL
        }
    )

# ---------------------------------------------------
# Load trained model
# ---------------------------------------------------

def load_model():

    if not os.path.exists(MODEL_PATH):
        print("Model not found:", MODEL_PATH)
        sys.exit(1)

    return joblib.load(MODEL_PATH)

# ---------------------------------------------------
# Read sensor data
# ---------------------------------------------------

def fetch_daily_aggregate():

    data = db.reference(
        f"devices/{DEVICE_ID}/daily_aggregate"
    ).get()

    if not data:
        print("No daily_aggregate data found.")
        sys.exit(0)

    return data

# ---------------------------------------------------
# Save advisory
# ---------------------------------------------------

def save_advisory(label, reading):

    db.reference(
        f"devices/{DEVICE_ID}/current_advisory"
    ).set(
        {
            "device_id": DEVICE_ID,
            "advisory_label": label,
            "input": reading
        }
    )

# ---------------------------------------------------
# Load subscriber tokens
# ---------------------------------------------------

def load_tokens():

    subscribers = db.reference(
        f"devices/{DEVICE_ID}/subscribers"
    ).get()

    if not subscribers:
        print("No subscribers registered.")
        return []

    tokens = []

    for user_id, info in subscribers.items():

        token = info.get("token")

        if token:
            tokens.append(token)

    return tokens

# ---------------------------------------------------
# Send notifications
# ---------------------------------------------------

def send_notifications(label, tokens):

    if not tokens:
        print("No tokens available.")
        return

    title = "🌱 Smart Farm Advisory"

    body = f"Device {DEVICE_ID}\n\n{label}"

    multicast = messaging.MulticastMessage(

        notification=messaging.Notification(
            title=title,
            body=body
        ),

        data={
            "device_id": DEVICE_ID,
            "advisory": label
        },

        tokens=tokens
    )

    response = messaging.send_each_for_multicast(multicast)

    print(
        f"Notifications:"
        f" {response.success_count} success,"
        f" {response.failure_count} failed"
    )

    # Remove invalid tokens

    if response.failure_count > 0:

        subscribers_ref = db.reference(
            f"devices/{DEVICE_ID}/subscribers"
        )

        subscribers = subscribers_ref.get()

        responses = response.responses

        index = 0

        for user_id, info in subscribers.items():

            token = info.get("token")

            if not token:
                continue

            if not responses[index].success:

                print("Removing invalid token:", user_id)

                subscribers_ref.child(user_id).delete()

            index += 1

# ---------------------------------------------------
# Main
# ---------------------------------------------------

def main():

    init_firebase()

    bundle = load_model()

    model = bundle["model"]
    encoder = bundle["label_encoder"]
    feature_order = bundle["feature_order"]

    reading = fetch_daily_aggregate()

    features = {
        "temp_max": reading["temp_max"],
        "temp_min": reading["temp_min"],
        "temp_mean": reading["temp_mean"],
        "humidity_mean": reading["humidity_mean"],
        "precipitation_mm": reading.get(
            "rain_intensity_avg",
            0
        )
    }

    df = pd.DataFrame(
        [features]
    )[feature_order]

    prediction = model.predict(df)

    label = encoder.inverse_transform(
        prediction
    )[0]

    print("Prediction:", label)

    save_advisory(label, features)

    should_notify = (
        NOTIFY_ON_ALL or
        label in NOTIFY_ON_LABELS
    )

    if should_notify:

        tokens = load_tokens()

        send_notifications(
            label,
            tokens
        )

    else:

        print("Notification skipped.")

if __name__ == "__main__":
    main()
