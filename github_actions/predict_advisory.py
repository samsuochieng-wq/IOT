"""
predict_advisory.py
--------------------
Reads latest sensor readings, aggregates over time window,
runs model (which now includes wind_speed_10m_mean and pressure_msl_mean),
adjusts advisory based on tomorrow's rain probability,
saves to Firebase, and emails subscribers.
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

# Email sent on every run
NOTIFY_ON_ALL = True

# Recommendations (same as before)
RECOMMENDATIONS = {
    "High Fungal Risk": {
        "emoji": "🍄",
        "summary": "Conditions currently favor fungal disease development.",
        "action": "Consider preventive fungicide application and improve airflow around plants.",
    },
    "Irrigate Immediately": {
        "emoji": "💧",
        "summary": "Hot, dry conditions with no rainfall detected.",
        "action": "Irrigation is recommended now to prevent crop water stress.",
    },
    "Delay Fertilizer": {
        "emoji": "🌧️",
        "summary": "Heavy rainfall detected or expected.",
        "action": "Hold off on fertilizer application - heavy rain risks runoff/leaching.",
    },
    "Normal / No Action": {
        "emoji": "✅",
        "summary": "Conditions are stable - no immediate action needed.",
        "action": "Continue routine monitoring.",
    },
    "Rain expected tomorrow – delay irrigation": {
        "emoji": "🌧️",
        "summary": "Rain forecast for tomorrow, irrigation not needed.",
        "action": "Delay irrigation until after the rain.",
    },
    "Irrigate today – rain possible": {
        "emoji": "⏳",
        "summary": "Rain possible tomorrow, but conditions dry today.",
        "action": "Irrigate today if needed; monitor forecast.",
    },
    "High Fungal Risk + Rain forecast": {
        "emoji": "⚠️",
        "summary": "High fungal risk combined with rain expected tomorrow.",
        "action": "Rain may increase fungal pressure. Consider preventive fungicide.",
    },
    "High Fungal Risk – rain possible": {
        "emoji": "⚠️",
        "summary": "High fungal risk and rain chance tomorrow.",
        "action": "Monitor fields closely. Rain could accelerate fungal spread.",
    },
    "Rain forecast – no immediate action": {
        "emoji": "🌧️",
        "summary": "Rain expected tomorrow, conditions currently stable.",
        "action": "No immediate action required. Check after rain.",
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
        logger.info(f"Feature order: {bundle.get('feature_order', [])}")
        return bundle
    except Exception:
        logger.exception("Failed to load model file.")
        sys.exit(1)


# ---------------------------------------------------
# Read sensor data (aggregated over time window)
# ---------------------------------------------------

def fetch_recent_aggregate(device_id: str, window_hours: int = 24):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    cutoff_iso = cutoff.isoformat()

    try:
        history_ref = db.reference(f"devices/{device_id}/history")
        all_history = history_ref.get()
    except Exception:
        logger.exception("Failed to read history from Realtime Database.")
        sys.exit(1)

    if not all_history:
        logger.warning("No history data found. Falling back to daily_aggregate.")
        return fetch_daily_aggregate(device_id)

    readings = []
    for key, record in all_history.items():
        ts = record.get('predicted_at')
        if not ts:
            continue
        if ts >= cutoff_iso:
            input_data = record.get('input')
            if input_data:
                readings.append(input_data)

    if not readings:
        logger.warning(f"No readings in the last {window_hours} hours. Falling back to daily_aggregate.")
        return fetch_daily_aggregate(device_id)

    df = pd.DataFrame(readings)
    # Ensure all expected columns exist; fill missing with 0
    expected_cols = ['temp_max', 'temp_min', 'temp_mean', 'humidity_mean', 'precipitation_mm',
                     'wind_speed_10m_mean', 'pressure_msl_mean']
    for col in expected_cols:
        if col not in df.columns:
            df[col] = 0

    agg = {
        'temp_max': df['temp_max'].max(),
        'temp_min': df['temp_min'].min(),
        'temp_mean': df['temp_mean'].mean(),
        'humidity_mean': df['humidity_mean'].mean(),
        'precipitation_mm': df['precipitation_mm'].sum(),
        'wind_speed_10m_mean': df['wind_speed_10m_mean'].mean(),
        'pressure_msl_mean': df['pressure_msl_mean'].mean(),
    }
    logger.info(f"Computed aggregate over {len(readings)} readings in the last {window_hours} hours.")
    return agg


def fetch_daily_aggregate(device_id: str):
    try:
        data = db.reference(f"devices/{device_id}/daily_aggregate").get()
    except Exception:
        logger.exception("Failed to read daily_aggregate from Realtime Database.")
        sys.exit(1)

    if not data:
        logger.info(f"No daily_aggregate data found for device {device_id}. Nothing to predict yet.")
        sys.exit(0)

    # Ensure new fields exist; if not, add defaults
    for field in ['wind_speed_10m_mean', 'pressure_msl_mean']:
        if field not in data:
            data[field] = 0
    return data


# ---------------------------------------------------
# Adjust advisory based on weather forecast
# ---------------------------------------------------

def adjust_advisory_with_weather(original_label, rain_prob):
    if rain_prob is None:
        return original_label, ""

    if rain_prob >= 60:
        if original_label == 'Irrigate Immediately':
            return "Rain expected tomorrow – delay irrigation", f"🌧️ Rain probability: {rain_prob}% tomorrow. Delay irrigation."
        elif original_label == 'Delay Fertilizer':
            return "Delay Fertilizer", f"🌧️ Rain probability: {rain_prob}% tomorrow. Fertilize after rain."
        elif original_label == 'High Fungal Risk':
            return "High Fungal Risk + Rain forecast", f"🌧️ Rain may increase fungal pressure. Monitor closely."
        else:
            return "Rain forecast – no immediate action", f"🌧️ Rain probability: {rain_prob}% tomorrow. Conditions stable."
    elif rain_prob >= 30:
        if original_label == 'Irrigate Immediately':
            return f"Irrigate today – rain possible ({rain_prob}%)", f"🌦️ Rain chance {rain_prob}% – consider irrigating today."
        elif original_label == 'High Fungal Risk':
            return "High Fungal Risk – rain possible", f"🌦️ Rain may increase risk. Check fields."
        else:
            return original_label, f"🌦️ Rain chance {rain_prob}% tomorrow."
    else:
        return original_label, ""


# ---------------------------------------------------
# Save advisory
# ---------------------------------------------------

def save_advisory(device_id: str, label: str, reading: dict, forecast_note: str = "", weather_forecast: dict = None):
    predicted_at = datetime.now(timezone.utc).isoformat()

    record = {
        "device_id": device_id,
        "advisory_label": label,
        "input": reading,
        "forecast_note": forecast_note,
        "predicted_at": predicted_at,
    }

    if weather_forecast:
        record["weather_forecast"] = weather_forecast

    logger.info(f"Saving advisory record: {record}")

    try:
        db.reference(f"devices/{device_id}/current_advisory").set(record)
        logger.info("Advisory written to Realtime Database (current_advisory).")
    except Exception:
        logger.exception("Failed to write current_advisory to Realtime Database.")

    try:
        db.reference(f"devices/{device_id}/history").push(record)
        logger.info("Advisory appended to history.")
    except Exception:
        logger.exception("Failed to append advisory to history.")


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

    logger.info(f"Loaded {len(emails)} subscriber email(s).")
    return emails


# ---------------------------------------------------
# Email generation (kept from previous)
# ---------------------------------------------------

def build_email_html(device_id: str, label: str, reading: dict, window_hours: int,
                     forecast_note: str = "", weather_forecast: dict = None) -> str:
    info = RECOMMENDATIONS.get(label, {
        "emoji": "ℹ️",
        "summary": "Advisory update available.",
        "action": "Check your dashboard for details.",
    })

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    weather_html = ""
    if weather_forecast and any(weather_forecast.values()):
        weather_html = '<div style="margin-top:16px;padding:12px;background:#f0f7fa;border-radius:6px;">'
        weather_html += '<p style="font-weight:bold;font-size:13px;margin:0 0 6px 0;color:#1a3a4a;">🌤️ Tomorrow\'s Forecast</p>'
        if weather_forecast.get('description'):
            weather_html += f'<p style="font-size:13px;margin:2px 0;">📝 {weather_forecast["description"].capitalize()}</p>'
        if weather_forecast.get('rain_prob') is not None:
            weather_html += f'<p style="font-size:13px;margin:2px 0;">🌧️ Rain probability: {weather_forecast["rain_prob"]}%</p>'
        if weather_forecast.get('wind_speed') is not None:
            weather_html += f'<p style="font-size:13px;margin:2px 0;">💨 Wind speed: {weather_forecast["wind_speed"]} m/s</p>'
        if weather_forecast.get('pressure') is not None:
            weather_html += f'<p style="font-size:13px;margin:2px 0;">📊 Pressure: {weather_forecast["pressure"]} hPa</p>'
        weather_html += '</div>'

    html = f"""<html>
    <body style="font-family:Arial,sans-serif;background:#f4f6f5;padding:24px;margin:0;">
    <div style="max-width:560px;margin:0 auto;background:#fff;border-radius:10px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,0.08);">
      <div style="background:#2f7d4f;padding:20px 24px;">
        <h1 style="color:#fff;font-size:20px;margin:0;">🌱 Smart Farm Advisory</h1>
        <p style="color:#d7ecdf;font-size:13px;margin:4px 0 0 0;">Device: {device_id}</p>
        <p style="color:#d7ecdf;font-size:12px;margin:4px 0 0 0;">Window: last {window_hours} hours</p>
      </div>
      <div style="padding:24px;">
        <div style="background:#f0f7f2;border-left:4px solid #2f7d4f;padding:14px 16px;border-radius:4px;margin-bottom:20px;">
          <p style="font-size:18px;font-weight:bold;margin:0 0 6px 0;color:#1f3d2b;">
            {info['emoji']} {label}
          </p>
          <p style="font-size:14px;margin:0;color:#3a4a3f;">{info['summary']}</p>
          {f'<p style="font-size:13px;margin-top:8px;color:#2f7d4f;">{forecast_note}</p>' if forecast_note else ''}
        </div>

        <p style="font-size:14px;color:#333;line-height:1.5;">
          <strong>Recommended action:</strong><br>
          {info['action']}
        </p>

        <table style="width:100%;border-collapse:collapse;margin-top:20px;font-size:13px;">
          <tr style="background:#f4f6f5;"><td style="padding:8px 10px;color:#666;">Max Temp</td><td style="padding:8px 10px;text-align:right;font-weight:bold;">{reading.get('temp_max', 'N/A')} °C</td></tr>
          <tr><td style="padding:8px 10px;color:#666;">Min Temp</td><td style="padding:8px 10px;text-align:right;font-weight:bold;">{reading.get('temp_min', 'N/A')} °C</td></tr>
          <tr style="background:#f4f6f5;"><td style="padding:8px 10px;color:#666;">Mean Temp</td><td style="padding:8px 10px;text-align:right;font-weight:bold;">{reading.get('temp_mean', 'N/A')} °C</td></tr>
          <tr><td style="padding:8px 10px;color:#666;">Humidity</td><td style="padding:8px 10px;text-align:right;font-weight:bold;">{reading.get('humidity_mean', 'N/A')} %</td></tr>
          <tr style="background:#f4f6f5;"><td style="padding:8px 10px;color:#666;">Precipitation</td><td style="padding:8px 10px;text-align:right;font-weight:bold;">{reading.get('precipitation_mm', 'N/A')} mm</td></tr>
          {f'<tr><td style="padding:8px 10px;color:#666;">Wind Speed</td><td style="padding:8px 10px;text-align:right;font-weight:bold;">{reading.get("wind_speed_10m_mean", "N/A")} m/s</td></tr>' if reading.get("wind_speed_10m_mean") is not None else ''}
          {f'<tr style="background:#f4f6f5;"><td style="padding:8px 10px;color:#666;">Pressure</td><td style="padding:8px 10px;text-align:right;font-weight:bold;">{reading.get("pressure_msl_mean", "N/A")} hPa</td></tr>' if reading.get("pressure_msl_mean") is not None else ''}
        </table>
        {weather_html}
        <p style="font-size:11px;color:#999;margin-top:24px;">Generated {timestamp} · Automated advisory.</p>
      </div>
    </div>
    </body></html>"""
    return html


def build_email_text(device_id: str, label: str, reading: dict, window_hours: int,
                     forecast_note: str = "", weather_forecast: dict = None) -> str:
    info = RECOMMENDATIONS.get(label, {"summary": "Advisory update available.", "action": "Check your dashboard."})
    text = f"Smart Farm Advisory - Device {device_id}\n\nAdvisory: {label}\n{info['summary']}\n"
    if forecast_note:
        text += f"{forecast_note}\n"
    text += f"\nRecommended action:\n{info['action']}\n\nReadings (last {window_hours} hours):\n"
    text += f"  Max Temp: {reading.get('temp_max', 'N/A')} C\n  Min Temp: {reading.get('temp_min', 'N/A')} C\n"
    text += f"  Mean Temp: {reading.get('temp_mean', 'N/A')} C\n  Humidity: {reading.get('humidity_mean', 'N/A')} %\n"
    text += f"  Precipitation: {reading.get('precipitation_mm', 'N/A')} mm\n"
    if reading.get('wind_speed_10m_mean') is not None:
        text += f"  Wind Speed: {reading['wind_speed_10m_mean']} m/s\n"
    if reading.get('pressure_msl_mean') is not None:
        text += f"  Pressure: {reading['pressure_msl_mean']} hPa\n"
    if weather_forecast:
        text += "\n--- Tomorrow's Forecast ---\n"
        if weather_forecast.get('description'):
            text += f"  Weather: {weather_forecast['description'].capitalize()}\n"
        if weather_forecast.get('rain_prob') is not None:
            text += f"  Rain probability: {weather_forecast['rain_prob']}%\n"
        if weather_forecast.get('wind_speed') is not None:
            text += f"  Wind speed: {weather_forecast['wind_speed']} m/s\n"
        if weather_forecast.get('pressure') is not None:
            text += f"  Pressure: {weather_forecast['pressure']} hPa\n"
    return text


# ---------------------------------------------------
# Send email (Brevo)
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
            logger.info(f"Email sent to {to_email}")
            return True
        try:
            error_detail = response.json()
        except ValueError:
            error_detail = response.text
        logger.error(f"Brevo API error ({response.status_code}) sending to {to_email}: {error_detail}")
        return False
    except requests.exceptions.RequestException:
        logger.exception(f"Network error sending email to {to_email}")
        return False


def send_all_emails(device_id: str, label: str, reading: dict, emails: list, window_hours: int,
                    forecast_note: str = "", weather_forecast: dict = None):
    if not emails:
        logger.info("No subscriber emails to notify.")
        return

    subject = f"🌱 Farm Advisory: {label} - Device {device_id}"
    html_body = build_email_html(device_id, label, reading, window_hours, forecast_note, weather_forecast)
    text_body = build_email_text(device_id, label, reading, window_hours, forecast_note, weather_forecast)

    logger.info("==============================")
    logger.info("Sending advisory emails")
    logger.info("==============================")
    logger.info(f"Recipients: {len(emails)}")

    success = 0
    for email in emails:
        if send_email(email, subject, html_body, text_body):
            success += 1
    logger.info(f"Success: {success} | Failed: {len(emails)-success}")


# ---------------------------------------------------
# Main
# ---------------------------------------------------

def main():
    validate_environment()
    init_firebase()

    device_id = os.environ["DEVICE_ID"]
    try:
        window_hours = int(os.environ.get("WINDOW_HOURS", "24"))
    except ValueError:
        window_hours = 24
    logger.info(f"Using aggregation window of {window_hours} hours.")

    # ---- Read environment variables ----
    rain_prob_str = os.environ.get("RAIN_PROB")
    today_wind_str = os.environ.get("TODAY_WIND")
    today_pressure_str = os.environ.get("TODAY_PRESSURE")
    tomorrow_wind_str = os.environ.get("TOMORROW_WIND")
    tomorrow_pressure_str = os.environ.get("TOMORROW_PRESSURE")
    tomorrow_desc = os.environ.get("TOMORROW_DESC")

    logger.info(f"RAIN_PROB={rain_prob_str}")
    logger.info(f"TODAY_WIND={today_wind_str}")
    logger.info(f"TODAY_PRESSURE={today_pressure_str}")
    logger.info(f"TOMORROW_WIND={tomorrow_wind_str}")
    logger.info(f"TOMORROW_PRESSURE={tomorrow_pressure_str}")
    logger.info(f"TOMORROW_DESC={tomorrow_desc}")

    # Build weather_forecast dict for tomorrow
    weather_forecast = {}
    if rain_prob_str:
        try:
            weather_forecast['rain_prob'] = int(rain_prob_str)
        except ValueError:
            pass
    if tomorrow_wind_str:
        try:
            weather_forecast['wind_speed'] = float(tomorrow_wind_str)
        except ValueError:
            pass
    if tomorrow_pressure_str:
        try:
            weather_forecast['pressure'] = float(tomorrow_pressure_str)
        except ValueError:
            pass
    if tomorrow_desc:
        weather_forecast['description'] = tomorrow_desc

    # Load model
    bundle = load_model()
    model = bundle["model"]
    encoder = bundle["label_encoder"]
    feature_order = bundle["feature_order"]  # includes new features

    # Read sensor aggregate from Firebase
    reading = fetch_recent_aggregate(device_id, window_hours)

    # Fill wind/pressure from today's API if missing or zero
    if (reading.get('wind_speed_10m_mean') is None or reading.get('wind_speed_10m_mean') == 0) and today_wind_str:
        reading['wind_speed_10m_mean'] = float(today_wind_str)
        logger.info(f"Filled wind_speed_10m_mean with today's API: {today_wind_str}")
    if (reading.get('pressure_msl_mean') is None or reading.get('pressure_msl_mean') == 0) and today_pressure_str:
        reading['pressure_msl_mean'] = float(today_pressure_str)
        logger.info(f"Filled pressure_msl_mean with today's API: {today_pressure_str}")

    # Ensure all features exist (fallback to 0)
    features = {
        "temp_max": reading.get("temp_max", 0),
        "temp_min": reading.get("temp_min", 0),
        "temp_mean": reading.get("temp_mean", 0),
        "humidity_mean": reading.get("humidity_mean", 0),
        "precipitation_mm": reading.get("precipitation_mm", 0),
        "wind_speed_10m_mean": reading.get("wind_speed_10m_mean", 0.0),
        "pressure_msl_mean": reading.get("pressure_msl_mean", 0.0),
    }
    logger.info(f"Features for model: {features}")

    # Run prediction
    try:
        df = pd.DataFrame([features])[feature_order]
        prediction = model.predict(df)
        original_label = encoder.inverse_transform(prediction)[0]
        logger.info(f"Original advisory: {original_label}")
    except Exception as e:
        logger.exception("Prediction failed.")
        sys.exit(1)

    # Adjust based on rain probability
    rain_prob = weather_forecast.get('rain_prob')
    adjusted_label, forecast_note = adjust_advisory_with_weather(original_label, rain_prob)
    logger.info(f"Adjusted label: {adjusted_label}, forecast_note: {forecast_note}")

    # Save to Firebase
    save_advisory(device_id, adjusted_label, features, forecast_note, weather_forecast)

    # Send emails
    emails = load_subscriber_emails(device_id)
    send_all_emails(device_id, adjusted_label, features, emails, window_hours, forecast_note, weather_forecast)

    logger.info("Script completed successfully.")


if __name__ == "__main__":
    main()
