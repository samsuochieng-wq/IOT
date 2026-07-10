"""
predict_advisory.py
--------------------
Reads the latest sensor aggregate for a device from Firebase Realtime Database,
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
    BREVO_API_KEY                  - Brevo API key (Settings -> SMTP & API -> API Keys)
    BREVO_SENDER_EMAIL             - a verified sender email in your Brevo account
    BREVO_SENDER_NAME              - display name for the sender, e.g. "Smart Farm Advisory"

Brevo's free plan includes 300 emails/day at no cost, no card required - just
sign up and verify a sender email or domain.
"""

import os
import sys
import json
import logging
from datetime import datetime, timezone

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

# During testing, email on every advisory (including "Normal / No Action").
# Set to False for production so subscribers only get emailed for urgent labels.
NOTIFY_ON_ALL = True

NOTIFY_ON_LABELS = {
    "High Fungal Risk",
    "Irrigate Immediately",
    "Delay Fertilizer",
}

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
# Read sensor data
# ---------------------------------------------------

def fetch_daily_aggregate(device_id: str):
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

    # Also append to history so graphs/trends have something to draw from.
    # push() generates a unique, time-ordered key - safe for many rapid writes,
    # unlike using a plain timestamp string which could collide.
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

def build_email_html(device_id: str, label: str, reading: dict) -> str:
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


def build_email_text(device_id: str, label: str, reading: dict) -> str:
    """Plain-text fallback for email clients that don't render HTML."""
    info = RECOMMENDATIONS.get(label, {"summary": "Advisory update available.", "action": "Check your dashboard."})
    return (
        f"Smart Farm Advisory - Device {device_id}\n\n"
        f"Advisory: {label}\n"
        f"{info['summary']}\n\n"
        f"Recommended action:\n{info['action']}\n\n"
        f"Readings:\n"
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

        # Brevo returns a JSON error body describing exactly what went wrong -
        # e.g. unverified sender, invalid API key, malformed recipient, etc.
        try:
            error_detail = response.json()
        except ValueError:
            error_detail = response.text

        logger.error(f"Brevo API error ({response.status_code}) sending to {to_email}: {error_detail}")
        return False

    except requests.exceptions.RequestException:
        logger.exception(f"Network error sending email to {to_email} via Brevo")
        return False


def send_all_emails(device_id: str, label: str, reading: dict, emails: list):
    if not emails:
        logger.info("No subscriber emails to notify.")
        return

    subject = f"🌱 Farm Advisory: {label} - Device {device_id}"
    html_body = build_email_html(device_id, label, reading)
    text_body = build_email_text(device_id, label, reading)

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

    bundle = load_model()
    model = bundle["model"]
    encoder = bundle["label_encoder"]
    feature_order = bundle["feature_order"]

    reading = fetch_daily_aggregate(device_id)

    features = {
        "temp_max": reading.get("temp_max"),
        "temp_min": reading.get("temp_min"),
        "temp_mean": reading.get("temp_mean"),
        "humidity_mean": reading.get("humidity_mean"),
        "precipitation_mm": reading.get("rain_intensity_avg", 0),
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

    should_notify = NOTIFY_ON_ALL or label in NOTIFY_ON_LABELS

    if should_notify:
        emails = load_subscriber_emails(device_id)
        send_all_emails(device_id, label, features, emails)
    else:
        logger.info(f"Label '{label}' not urgent - skipping email notifications.")


if __name__ == "__main__":
    main()
