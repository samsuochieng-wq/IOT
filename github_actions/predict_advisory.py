"""
predict_advisory.py
--------------------
Reads the latest sensor readings for a device from Firebase Realtime Database,
computes aggregates over a configurable time window (e.g., 6 hours),
runs the trained model to produce an advisory label, writes the result back to
the database, and emails every registered subscriber an HTML advisory notice
via Brevo's transactional email API.

This replaces Firebase Cloud Messaging (push notifications) entirely - no FCM
tokens, no messaging_admin, no mobile app dependency. Subscribers are identified
purely by email address, matching this Realtime Database structure:

    /devices/{device_id}/subscribers/{sanitized_email_key}
        email: "someone@example.com"
        registered: true
        registered_at: "2026-07-09T10:57:21.372928+00:00"

Required environment variables:
    FIREBASE_SERVICE_ACCOUNT_JSON  - full contents of the Firebase service account key
    FIREBASE_DB_URL                - e.g. https://your-project-default-rtdb.firebaseio.com
    DEVICE_ID                      - e.g. esp32_001
    BREVO_API_KEY                  - Brevo API key
    BREVO_SENDER_EMAIL             - a verified sender email in your Brevo account
    BREVO_SENDER_NAME              - display name for the sender, e.g. "Smart Farm Advisory"
    WINDOW_HOURS                   - (optional) number of hours to look back for aggregation, default 24
"""

import os
import sys
import json
import logging
from datetime import datetime, timezone, timedelta

import requests
import joblib
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db

# ---------------------------------------------------
# Logging
# ---------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("predict_advisory")

# ---------------------------------------------------
# Configuration
# ---------------------------------------------------

MODEL_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "models",
    "farm_advisory_model.joblib",
)

BREVO_SEND_URL = "https://api.brevo.com/v3/smtp/email"

REQUIRED_ENV_VARS = [
    "FIREBASE_SERVICE_ACCOUNT_JSON",
    "FIREBASE_DB_URL",
    "DEVICE_ID",
    "BREVO_API_KEY",
    "BREVO_SENDER_EMAIL",
    "BREVO_SENDER_NAME",
]

# Email will be sent on every run (every 6 hours) - this gives the user regular updates.
# If you want to limit to only certain labels, change this to False.
NOTIFY_ON_ALL = True

# Human-readable guidance shown in the email body for each advisory label.
RECOMMENDATIONS = {
    "High Fungal Risk": {
        "emoji": "🍄",
        "summary": "Conditions currently favor fungal disease development.",
        "action": "Consider preventive fungicide application and improve airflow "
                   "around plants if possible. Monitor leaves closely over the next 24-48 hours.",
    },
    "Irrigate Immediately": {
        "emoji": "💧",
        "summary": "Hot, dry conditions with no rainfall detected.",
        "action": "Irrigation is recommended now to prevent crop water stress.",
    },
    "Delay Fertilizer": {
        "emoji": "🌧️",
        "summary": "Heavy rainfall detected or expected.",
        "action": "Hold off on fertilizer application - heavy rain risks runoff/leaching, "
                   "wasting product and potentially affecting nearby water sources.",
    },
    "Normal / No Action": {
        "emoji": "✅",
        "summary": "Conditions are stable - no immediate action needed.",
        "action": "Continue routine monitoring. No intervention required at this time.",
    },
}

# ---------------------------------------------------
# Environment validation
# ---------------------------------------------------

def validate_environment():
    missing = [var for var in REQUIRED_ENV_VARS if not os.environ.get(var)]
    if missing:
        logger.error(f"Missing required environment variables: {missing}")
        sys.exit(1)


# ---------------------------------------------------
# Firebase
# ---------------------------------------------------

def init_firebase():
    try:
        service_account = json.loads(os.environ["FIREBASE_SERVICE_ACCOUNT_JSON"])
        cred = credentials.Certificate(service_account)
        firebase_admin.initialize_app(cred, {"databaseURL": os.environ["FIREBASE_DB_URL"]})
        logger.info("Firebase initialized successfully.")
    except Exception:
        logger.exception("Failed to initialize Firebase.")
        sys.exit(1)


# ---------------------------------------------------
# Load trained model
# ---------------------------------------------------

def load_model():
    if not os.path.exists(MODEL_PATH):
        logger.error(f"Model file not found at: {MODEL_PATH}")
        logger.error("Make sure farm_advisory_model.joblib is committed under models/")
        sys.exit(1)

    try:
        bundle = joblib.load(MODEL_PATH)
        logger.info("Model loaded successfully.")
        return bundle
    except Exception:
        logger.exception("Failed to load model file.")
        sys.exit(1)


# ---------------------------------------------------
# Read sensor data (aggregated over time window)
# ---------------------------------------------------

def fetch_recent_aggregate(device_id: str, window_hours: int = 24):
    """
    Fetches sensor readings from the history node for the last `window_hours` hours,
    computes:
        - temp_max, temp_min, temp_mean
        - humidity_mean
        - precipitation_mm (sum)
    If there are no readings in that window, falls back to the daily_aggregate node.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    cutoff_iso = cutoff.isoformat()

    try:
        history_ref = db.reference(f"devices/{device_id}/history")
        # We need to query all history entries and filter by timestamp.
        # Firebase Realtime Database doesn't support date range queries on string keys,
        # so we fetch all and filter in Python. For a production system with many records,
        # consider storing timestamps as numbers or using a separate index.
        all_history = history_ref.get()
    except Exception:
        logger.exception("Failed to read history from Realtime Database.")
        sys.exit(1)

    if not all_history:
        logger.warning("No history data found. Falling back to daily_aggregate.")
        return fetch_daily_aggregate(device_id)

    readings = []
    for key, record in all_history.items():
        # Each record should contain 'predicted_at' or we can use the key if it's a timestamp.
        # Our previous save uses predicted_at, but we can also look for 'input' field.
        # We'll use the record's 'predicted_at' if present, else fallback to the key.
        ts = record.get('predicted_at')
        if not ts:
            # If the key is a timestamp string, use it.
            # But keys are push() IDs, not timestamps. So we need predicted_at.
            continue
        if ts >= cutoff_iso:
            # This record is within the window
            input_data = record.get('input')
            if input_data:
                readings.append(input_data)

    if not readings:
        logger.warning(f"No readings in the last {window_hours} hours. Falling back to daily_aggregate.")
        return fetch_daily_aggregate(device_id)

    # Compute aggregates
    df = pd.DataFrame(readings)
    # Ensure columns exist; if missing, set defaults.
    temp_cols = ['temp_mean', 'temp_min', 'temp_max']
    for col in temp_cols:
        if col not in df.columns:
            df[col] = df['temp_mean'] if 'temp_mean' in df.columns else 0  # fallback
    if 'humidity_mean' not in df.columns:
        df['humidity_mean'] = 70  # fallback
    if 'precipitation_mm' not in df.columns:
        df['precipitation_mm'] = 0

    agg = {
        'temp_max': df['temp_max'].max(),
        'temp_min': df['temp_min'].min(),
        'temp_mean': df['temp_mean'].mean(),
        'humidity_mean': df['humidity_mean'].mean(),
        'precipitation_mm': df['precipitation_mm'].sum(),
    }
    logger.info(f"Computed aggregate over {len(readings)} readings in the last {window_hours} hours.")
    return agg


def fetch_daily_aggregate(device_id: str):
    """Fallback: read from the daily_aggregate node (legacy)"""
    try:
        data = db.reference(f"devices/{device_id}/daily_aggregate").get()
    except Exception:
        logger.exception("Failed to read daily_aggregate from Realtime Database.")
        sys.exit(1)

    if not data:
        logger.info(f"No daily_aggregate data found for device {device_id}. Nothing to predict yet.")
        sys.exit(0)

    return data


# ---------------------------------------------------
# Save advisory
# ---------------------------------------------------

def save_advisory(device_id: str, label: str, reading: dict):
    predicted_at = datetime.now(timezone.utc).isoformat()

    record = {
        "device_id": device_id,
        "advisory_label": label,
        "input": reading,
        "predicted_at": predicted_at,
    }

    try:
        db.reference(f"devices/{device_id}/current_advisory").set(record)
        logger.info(f"Advisory written to Realtime Database: {label}")
    except Exception:
        logger.exception("Failed to write current_advisory to Realtime Database.")

    # Append to history
    try:
        db.reference(f"devices/{device_id}/history").push(record)
        logger.info("Advisory also appended to history.")
    except Exception:
        logger.exception("Failed to append advisory to history - current_advisory was still saved.")


# ---------------------------------------------------
# Load subscriber emails
# ---------------------------------------------------

def load_subscriber_emails(device_id: str) -> list:
    try:
        subscribers = db.reference(f"devices/{device_id}/subscribers").get()
    except Exception:
        logger.exception("Failed to read subscribers from Realtime Database.")
        return []

    if not subscribers:
        logger.info("No subscribers registered for this device.")
        return []

    emails = []
    for key, info in subscribers.items():
        if not isinstance(info, dict):
            continue
        if not info.get("registered", False):
            continue
        email = info.get("email")
        if email:
            emails.append(email)
        else:
            logger.warning(f"Subscriber record '{key}' has no email field - skipping.")

    logger.info(f"Loaded {len(emails)} subscriber email(s).")
    return emails


# ---------------------------------------------------
# Email generation
# ---------------------------------------------------

def build_email_html(device_id: str, label: str, reading: dict, window_hours: int) -> str:
    info = RECOMMENDATIONS.get(label, {
        "emoji": "ℹ️",
        "summary": "Advisory update available.",
        "action": "Check your dashboard for details.",
    })

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    html = f"""\
<html>
  <body style="font-family: Arial, sans-serif; background-color: #f4f6f5; padding: 24px; margin: 0;">
    <div style="max-width: 560px; margin: 0 auto; background-color: #ffffff; border-radius: 10px; overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,0.08);">

      <div style="background-color: #2f7d4f; padding: 20px 24px;">
        <h1 style="color: #ffffff; font-size: 20px; margin: 0;">🌱 Smart Farm Advisory</h1>
        <p style="color: #d7ecdf; font-size: 13px; margin: 4px 0 0 0;">Device: {device_id}</p>
        <p style="color: #d7ecdf; font-size: 12px; margin: 4px 0 0 0;">Window: last {window_hours} hours</p>
      </div>

      <div style="padding: 24px;">
        <div style="background-color: #f0f7f2; border-left: 4px solid #2f7d4f; padding: 14px 16px; border-radius: 4px; margin-bottom: 20px;">
          <p style="font-size: 18px; font-weight: bold; margin: 0 0 6px 0; color: #1f3d2b;">
            {info['emoji']} {label}
          </p>
          <p style="font-size: 14px; margin: 0; color: #3a4a3f;">{info['summary']}</p>
        </div>

        <p style="font-size: 14px; color: #333333; line-height: 1.5;">
          <strong>Recommended action:</strong><br>
          {info['action']}
        </p>

        <table style="width: 100%; border-collapse: collapse; margin-top: 20px; font-size: 13px;">
          <tr style="background-color: #f4f6f5;">
            <td style="padding: 8px 10px; color: #666;">Max Temp</td>
            <td style="padding: 8px 10px; text-align: right; font-weight: bold;">{reading.get('temp_max', 'N/A')} °C</td>
          </tr>
          <tr>
            <td style="padding: 8px 10px; color: #666;">Min Temp</td>
            <td style="padding: 8px 10px; text-align: right; font-weight: bold;">{reading.get('temp_min', 'N/A')} °C</td>
          </tr>
          <tr style="background-color: #f4f6f5;">
            <td style="padding: 8px 10px; color: #666;">Mean Temp</td>
            <td style="padding: 8px 10px; text-align: right; font-weight: bold;">{reading.get('temp_mean', 'N/A')} °C</td>
          </tr>
          <tr>
            <td style="padding: 8px 10px; color: #666;">Humidity</td>
            <td style="padding: 8px 10px; text-align: right; font-weight: bold;">{reading.get('humidity_mean', 'N/A')} %</td>
          </tr>
          <tr style="background-color: #f4f6f5;">
            <td style="padding: 8px 10px; color: #666;">Precipitation</td>
            <td style="padding: 8px 10px; text-align: right; font-weight: bold;">{reading.get('precipitation_mm', 'N/A')} mm</td>
          </tr>
        </table>

        <p style="font-size: 11px; color: #999999; margin-top: 24px;">
          Generated {timestamp} · This is an automated advisory from your farm monitoring system.
        </p>
      </div>
    </div>
  </body>
</html>
"""
    return html


def build_email_text(device_id: str, label: str, reading: dict, window_hours: int) -> str:
    info = RECOMMENDATIONS.get(label, {"summary": "Advisory update available.", "action": "Check your dashboard."})
    return (
        f"Smart Farm Advisory - Device {device_id}\n\n"
        f"Advisory: {label}\n"
        f"{info['summary']}\n\n"
        f"Recommended action:\n{info['action']}\n\n"
        f"Readings (last {window_hours} hours):\n"
        f"  Max Temp: {reading.get('temp_max', 'N/A')} C\n"
        f"  Min Temp: {reading.get('temp_min', 'N/A')} C\n"
        f"  Mean Temp: {reading.get('temp_mean', 'N/A')} C\n"
        f"  Humidity: {reading.get('humidity_mean', 'N/A')} %\n"
        f"  Precipitation: {reading.get('precipitation_mm', 'N/A')} mm\n"
    )


# ---------------------------------------------------
# Send email (Brevo transactional email API)
# ---------------------------------------------------

def send_email(to_email: str, subject: str, html_body: str, text_body: str) -> bool:
    api_key = os.environ["BREVO_API_KEY"]
    sender_email = os.environ["BREVO_SENDER_EMAIL"]
    sender_name = os.environ["BREVO_SENDER_NAME"]

    headers = {
        "accept": "application/json",
        "api-key": api_key,
        "content-type": "application/json",
    }

    payload = {
        "sender": {"name": sender_name, "email": sender_email},
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": html_body,
        "textContent": text_body,
    }

    try:
        response = requests.post(BREVO_SEND_URL, headers=headers, json=payload, timeout=20)

        if response.status_code in (200, 201):
            return True

        try:
            error_detail = response.json()
        except ValueError:
            error_detail = response.text

        logger.error(f"Brevo API error ({response.status_code}) sending to {to_email}: {error_detail}")
        return False

    except requests.exceptions.RequestException:
        logger.exception(f"Network error sending email to {to_email} via Brevo")
        return False


def send_all_emails(device_id: str, label: str, reading: dict, emails: list, window_hours: int):
    if not emails:
        logger.info("No subscriber emails to notify.")
        return

    subject = f"🌱 Farm Advisory: {label} - Device {device_id}"
    html_body = build_email_html(device_id, label, reading, window_hours)
    text_body = build_email_text(device_id, label, reading, window_hours)

    logger.info("==============================")
    logger.info("Sending advisory emails")
    logger.info("==============================")
    logger.info(f"Recipients: {len(emails)}")

    success_count = 0
    failure_count = 0

    for email in emails:
        sent = send_email(email, subject, html_body, text_body)
        if sent:
            success_count += 1
            logger.info(f"  -> {email}: SUCCESS")
        else:
            failure_count += 1
            logger.info(f"  -> {email}: FAILED")

    logger.info("========== EMAIL RESULT ==========")
    logger.info(f"Success: {success_count} | Failed: {failure_count}")


# ---------------------------------------------------
# Main
# ---------------------------------------------------

def main():
    validate_environment()
    init_firebase()

    device_id = os.environ["DEVICE_ID"]
    # Get window hours from environment, default 24
    try:
        window_hours = int(os.environ.get("WINDOW_HOURS", "24"))
    except ValueError:
        window_hours = 24
    logger.info(f"Using aggregation window of {window_hours} hours.")

    bundle = load_model()
    model = bundle["model"]
    encoder = bundle["label_encoder"]
    feature_order = bundle["feature_order"]

    # Read and aggregate sensor data over the specified window
    reading = fetch_recent_aggregate(device_id, window_hours)

    features = {
        "temp_max": reading.get("temp_max"),
        "temp_min": reading.get("temp_min"),
        "temp_mean": reading.get("temp_mean"),
        "humidity_mean": reading.get("humidity_mean"),
        "precipitation_mm": reading.get("precipitation_mm", 0),
    }

    missing = [k for k, v in features.items() if v is None]
    if missing:
        logger.error(f"Missing required fields in sensor data: {missing}")
        sys.exit(1)

    try:
        df = pd.DataFrame([features])[feature_order]
        prediction = model.predict(df)
        label = encoder.inverse_transform(prediction)[0]
    except Exception:
        logger.exception("Prediction failed.")
        sys.exit(1)

    logger.info(f"Predicted advisory for {device_id}: {label}")

    save_advisory(device_id, label, features)

    # Send email every time (since we're now running every 6 hours)
    emails = load_subscriber_emails(device_id)
    send_all_emails(device_id, label, features, emails, window_hours)


if __name__ == "__main__":
    main()
