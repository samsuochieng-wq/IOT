# No-Card Firebase Pipeline (Cloud Functions + Storage Replacement)

## Why this exists

Firebase now requires the paid Blaze plan (a linked billing card) for two products
we were relying on:
- **Cloud Storage** (where the model file lived)
- **Cloud Functions** (where inference + registration code ran)

Even though usage would likely stay within the free quota on Blaze, Blaze still
requires a card on file. This folder replaces both with genuinely free, no-card
alternatives, while keeping everything else (Realtime Database, Firestore, FCM)
exactly as before, since none of those require Blaze.

## What changed

| Old (needs Blaze/card) | New (no card required) |
|---|---|
| Cloud Storage (model file) | Model file committed directly into the repo under `models/` |
| Cloud Function `predict_advisory` | GitHub Actions scheduled workflow running `predict_advisory.py` |
| Cloud Function `register_subscription` | Flask app deployed free on Render.com |
| Realtime Database | **unchanged** - free on Spark |
| Firestore | **unchanged** - free on Spark |
| FCM | **unchanged** - free unconditionally, any plan |

## Setup steps

### 1. Get a Firebase service account key (free, no billing required)
Firebase Console → Project Settings → Service Accounts → "Generate new private key".
This downloads a JSON file. This credential lets your code talk to RTDB, Firestore,
and FCM - none of which need Blaze. Keep this file secret; never commit it to the repo.

### 2. Put your trained model in the repo
Copy `farm_advisory_model.joblib` (from the Colab notebook) into `models/` in this
folder before pushing to GitHub.

### 3. Push this folder to a GitHub repository

### 4. Set up the GitHub Actions secret
In your repo: Settings → Secrets and variables → Actions → New repository secret
- Name: `FIREBASE_SERVICE_ACCOUNT_JSON`
- Value: paste the entire contents of the service account JSON file from step 1

### 5. Edit the workflow file
In `.github/workflows/predict_advisory.yml`, update:
- `FIREBASE_DB_URL` to your actual Realtime Database URL
- `DEVICE_ID` to your actual device ID
- The `cron` schedule if you want a different cadence

Commit and push. Test it immediately without waiting for the schedule: go to the
Actions tab on GitHub → "Predict Farm Advisory" → "Run workflow" (this is what
`workflow_dispatch` in the yaml enables).

### 6. Deploy the registration endpoint on Render.com (free, no card)
1. Sign up at render.com (no card required for free tier)
2. New → Web Service → connect your GitHub repo, point it at `register_endpoint/`
3. Build command: `pip install -r requirements.txt`
4. Start command: `gunicorn app:app`
5. Add environment variable `FIREBASE_SERVICE_ACCOUNT_JSON` with the same JSON
   contents as step 4
6. Deploy — Render gives you a public URL, e.g. `https://your-app.onrender.com`

Your future mobile app calls `POST https://your-app.onrender.com/register_subscription`
with `{ "user_id": ..., "fcm_token": ..., "device_id": ... }` — same contract as before.

## Trade-offs of this approach vs. paying for Blaze

- **GitHub Actions cron** has a minimum granularity of about 5 minutes and GitHub
  doesn't guarantee exact-time execution on the free tier (a few minutes of drift
  is normal) - fine for daily/hourly farm advisories, not fine if you needed
  second-level precision.
- **Render free tier spins down when idle** - the registration endpoint will have
  a cold-start delay (several seconds) on its first call after inactivity. Since
  users register infrequently (once per device link), this is a reasonable trade-off.
- If your project grows to the point where you're comfortable adding a card, moving
  back to Cloud Functions/Storage on Blaze is a straightforward swap since the
  actual Python logic is nearly identical - it's just the hosting layer that changes.

## Security note (unchanged from before)

The registration endpoint still trusts whatever `user_id` is sent in the request
body. Add Firebase Auth ID token verification before this goes to real users, so
the endpoint checks a signed token instead of trusting a client-supplied ID.
