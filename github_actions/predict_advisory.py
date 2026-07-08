"""
predict_advisory.py
--------------------
Standalone script (NOT a Cloud Function) meant to be run by GitHub Actions on a
schedule. Avoids Cloud Functions and Cloud Storage entirely, since both now
require the paid Blaze plan (linked billing card) on Firebase - even for
free-tier usage.

This script:
1. Loads the trained model directly from the repo (models/farm_advisory_model.joblib)
   - no Cloud Storage involved.
2. Reads the latest daily aggregate for a device from Realtime Database via the
   Admin SDK (RTDB is free on the no-cost Spark plan - no card needed).
3. Predicts an advisory label.
4. Writes the result back to RTDB.
5. If the label is urgent, looks up subscribed users in Firestore (also free on
   Spark) and sends a push notification via FCM (unconditionally free, any plan).

Auth: uses a Firebase service account JSON key. Generating and using a service
account key does NOT require Blaze/billing - it's just a credential, free on
any plan, for any Spark-tier product (RTDB, Firestore, FCM).

Required GitHub Actions repo secret:
    FIREBASE_SERVICE_ACCOUNT_JSON  -> the full contents of your service account key file

Required environment variables (set in the workflow file):
    FIREBASE_DB_URL   e.g. https://your-project-id-default-rtdb.firebaseio.com
    DEVICE_ID         e.g. esp32_001
"""

import os
import sys
import json
import joblib
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db, firestore, messaging

MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "models", "farm_advisory_model.joblib")
FIREBASE_DB_URL = os.environ["FIREBASE_DB_URL"]
DEVICE_ID = os.environ["DEVICE_ID"]

# Advisory labels urgent enough to warrant a push notification.
NOTIFY_ON_LABELS = {"High Fungal Risk", "Irrigate Immediately", "Delay Fertilizer"}


def init_firebase():
    service_account_info = json.loads(os.environ["FIREBASE_SERVICE_ACCOUNT_JSON"])
    cred = credentials.Certificate(service_account_info)
    firebase_admin.initialize_app(cred, {"databaseURL": FIREBASE_DB_URL})
    return firestore.client()


def load_model_bundle():
    if not os.path.exists(MODEL_PATH):
        print(f"ERROR: model file not found at {MODEL_PATH}")
        print("Make sure farm_advisory_model.joblib is committed to the repo under models/")
        sys.exit(1)
    return joblib.load(MODEL_PATH)


def fetch_latest_reading(device_id: str):
    ref = db.reference(f"/devices/{device_id}/daily_aggregate")
    data = ref.get()
    if not data:
        print(f"No daily_aggregate data found for device {device_id}. Nothing to predict yet.")
        sys.exit(0)  # not an error - just no data yet, exit cleanly so the workflow doesn't fail
    return data


def get_subscribed_tokens(fs_client, device_id: str):
    subs_ref = fs_client.collection("devices").document(device_id).collection("subscribers")
    subscriber_ids = [doc.id for doc in subs_ref.stream()]

    user_tokens = []
    for user_id in subscriber_ids:
        user_doc = fs_client.collection("users").document(user_id).get()
        if user_doc.exists:
            tokens = user_doc.to_dict().get("fcm_tokens", [])
            if tokens:
                user_tokens.append((user_id, tokens))
    return user_tokens


def send_notifications(fs_client, device_id: str, advisory_label: str, user_tokens):
    if not user_tokens:
        print("No subscribers to notify for this device.")
        return

    body_map = {
        "High Fungal Risk": f"Device {device_id}: conditions favor fungal disease. Consider preventive spraying.",
        "Irrigate Immediately": f"Device {device_id}: hot and dry with no rain. Irrigation recommended now.",
        "Delay Fertilizer": f"Device {device_id}: heavy rain detected. Hold off on fertilizer application.",
    }
    body = body_map.get(advisory_label, f"Device {device_id}: advisory update - {advisory_label}")
    all_tokens = [token for _, tokens in user_tokens for token in tokens]

    message = messaging.MulticastMessage(
        notification=messaging.Notification(title="Farm Advisory Alert", body=body),
        data={"device_id": device_id, "advisory_label": advisory_label},
        tokens=all_tokens,
    )
    response = messaging.send_each_for_multicast(message)
    print(f"Notifications sent: {response.success_count} succeeded, {response.failure_count} failed.")

    if response.failure_count > 0:
        for idx, resp in enumerate(response.responses):
            if not resp.success:
                bad_token = all_tokens[idx]
                matching = fs_client.collection("users").where("fcm_tokens", "array_contains", bad_token).stream()
                for doc in matching:
                    doc.reference.update({"fcm_tokens": firestore.ArrayRemove([bad_token])})
                print(f"Removed invalid token from user records: {bad_token[:12]}...")


def main():
    fs_client = init_firebase()
    bundle = load_model_bundle()
    model = bundle["model"]
    label_encoder = bundle["label_encoder"]
    expected_features = bundle["feature_order"]

    reading = fetch_latest_reading(DEVICE_ID)

    # NOTE: rain_intensity_avg is a 0-1 sensor proxy, not calibrated mm - retrain
    # the model on this same scale before relying on this in production.
    live_reading = {
        "temp_max": reading.get("temp_max"),
        "temp_min": reading.get("temp_min"),
        "temp_mean": reading.get("temp_mean"),
        "humidity_mean": reading.get("humidity_mean"),
        "precipitation_mm": reading.get("rain_intensity_avg", 0.0),
    }

    missing = [k for k, v in live_reading.items() if v is None]
    if missing:
        print(f"ERROR: missing required fields in sensor data: {missing}")
        sys.exit(1)

    live_df = pd.DataFrame([live_reading])[expected_features]
    prediction_encoded = model.predict(live_df)
    advisory_label = label_encoder.inverse_transform(prediction_encoded)[0]

    print(f"Predicted advisory for {DEVICE_ID}: {advisory_label}")

    result = {
        "device_id": DEVICE_ID,
        "advisory_label": advisory_label,
        "input": live_reading,
    }
    db.reference(f"/devices/{DEVICE_ID}/current_advisory").set(result)

    if advisory_label in NOTIFY_ON_LABELS:
        user_tokens = get_subscribed_tokens(fs_client, DEVICE_ID)
        send_notifications(fs_client, DEVICE_ID, advisory_label, user_tokens)
    else:
        print("Advisory not urgent enough to notify - skipping push notifications.")


if __name__ == "__main__":
    main()
