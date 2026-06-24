# Shreeji Garage Public

Railway-deployed Flask app for Shreeji Auto Service.

This repo serves:

- Customer booking portal
- Lightweight web admin at `/admin/login`

The web admin is intended for on-the-go garage operations:

- Dashboard
- Slot Management
- Check-In
- Booking Requests
- Walk-in Entry

Both the public app and the separate desktop admin app use the same Neon
PostgreSQL database, so bookings and operational updates stay in sync.

## Run locally

```powershell
pip install -r requirements.txt
python app.py
```

## Deploy

Railway starts the app with:

```text
web: gunicorn app:app
```

Set `DATABASE_URL` in Railway Variables to the raw Neon PostgreSQL connection
URL.

Set `WEB_ADMIN_PIN` in Railway Variables to require a PIN in addition to an
admin ID or phone number at `/admin/login`.

## Note
Full desktop-only features such as HR, salary, attendance, workers, and local
packaging belong in the separate desktop admin repo/app. They are not registered
in this Railway-facing app.

## Admin Email OTP Login (Temporarily Disabled)

Admin IDs such as `ADMIN001` currently log in directly. The email OTP service is kept in the codebase for later re-enable.
Set these environment variables in `.env` locally and in Railway/production:

```text
ADMIN_OTP_EMAIL=owner@example.com
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USE_TLS=1
SMTP_USERNAME=your-smtp-username
SMTP_PASSWORD=your-smtp-app-password
SMTP_FROM_EMAIL=your-sender-email@example.com
```

Customer login is unchanged. If SMTP is not configured during local development,
the OTP can be generated for local testing and written through the normal app log path when the route flow is re-enabled.
