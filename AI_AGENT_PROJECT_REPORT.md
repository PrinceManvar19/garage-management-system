# AI Agent Project Report

## 1. Project Snapshot

- Project: Garage Management System
- Stack: Python + Flask + SQLite + Jinja templates + vanilla CSS/JS
- Entrypoint: `app.py`
- Production command: `gunicorn app:app` from `Procfile`
- Database file in active use: `garage.db`
- Date of this snapshot: 2026-04-17

This is a server-rendered Flask application for a motorcycle/service garage. It supports customer registration/login, service booking, admin approval/rejection, vehicle check-in, completion, slot management, and CSV export.

## 2. High-Level Architecture

The app mostly follows a layered structure:

- `routes/`: Flask blueprints and HTTP endpoints
- `services/`: business logic and orchestration
- `models/`: direct SQLite queries and schema/bootstrap code
- `templates/`: Jinja HTML pages
- `static/`: CSS, JS, images
- `utils/`: shared constants/helpers
- `data/`: legacy JSON seed data and some DB artifacts
- `backup/`: auto-created DB backups

Typical request flow:

1. Browser hits a route in `routes/*`
2. Route calls service functions in `services/*`
3. Service calls model functions in `models/*`
4. Models use `models.db.get_db()` for SQLite access
5. Route renders a Jinja template or returns JSON/redirect

Important exception: some routes still access `get_db()` directly instead of going through services/models.

## 3. Boot Flow

`app.py` does the following:

- creates the Flask app
- sets a hardcoded `secret_key`
- points `app.config["DATABASE"]` to `garage.db` in repo root
- initializes DB/schema through `models.db.init_app(app)`
- performs an automatic DB backup on startup
- syncs `session["user"]` before every request
- registers blueprints:
  - `main_bp`
  - `auth_bp`
  - `customer_bp`
  - `admin_bp`

Notable startup behavior:

- `perform_auto_backup()` runs every app startup and keeps the latest 5 DB backups.
- `models.db.init_app()` runs migrations and JSON-to-SQLite import logic during startup.

## 4. Directory Map

### Root

- `app.py`: Flask app factory and startup hooks
- `check.py`: lightweight admin page smoke test using Flask test client
- `garage.db`: main SQLite database
- `logs.txt`: append-only app/activity log
- `TODO.md`: current feature/refactor checklist
- `README.md`: minimal setup notes
- `requirements.txt`: Flask, Werkzeug, gunicorn
- `Procfile`: deployment entrypoint

### `routes/`

- `main_routes.py`: home page only
- `auth_routes.py`: login, registration, logout, find-ID flow
- `customer_routes.py`: dashboard, booking, vehicle APIs
- `admin_routes.py`: admin dashboard, slots, bookings, walk-in, check-in, export, status changes

### `services/`

- `auth_service.py`: login resolution + session payload shaping
- `booking_service.py`: booking lifecycle and booking enrichment
- `slot_service.py`: slot calculations and availability

### `models/`

- `db.py`: SQLite connection, schema creation, migrations, data seeding
- `booking_model.py`: CRUD/search/status updates for bookings
- `customer_model.py`: customer lookup/creation/search + vehicle lookup
- `admin_model.py`: admin lookup
- `slot_model.py`: slot CRUD helpers

### `templates/`

Main templates:

- `home.html`
- `login.html`
- `register.html`
- `find_id.html`
- `dashboard.html`
- `book.html`
- `checkin.html`
- `admin.html`
- `admin_bookings.html`
- `admin_slots.html`
- `admin_walkin.html`
- `admin_export.html`
- `base.html`
- `admin_base.html`

Potentially unused or not currently referenced in routes:

- `my_bookings.html`

### `static/`

- `static/css/style.css`: main styling
- `static/js/toasts.js`: UI toast behavior
- `static/images/logo1.png`
- `static/images/brands/*.svg`

## 5. Route Overview

### Public/Main

- `/`: home page

### Auth

- `/login`: login by phone or legacy ID
- `/register`: customer registration
- `/logout`: clear session
- `/find-id`: recover customer ID by matching name + phone + vehicle

### Customer

- `/dashboard`: customer dashboard
- `/book`: GET booking form, POST create booking
- `/api/vehicles/<identifier>`: fetch customer vehicles by phone or customer ID
- `/api/vehicles/add`: add a vehicle for the logged-in customer

### Admin

- `/admin`: dashboard
- `/admin/bookings`: filtered booking list
- `/admin/slots`: slot management page
- `/admin/walkin`: create same-day walk-in booking
- `/admin/export`: export UI page
- `/admin/checkin/verify`: verify booking before check-in
- `/admin/set-slots`: update slot totals
- `/admin/approve/<booking_id>`: approve pending booking
- `/admin/reject/<booking_id>`: reject pending booking
- `/admin/checkin/<booking_id>`: move approved booking to checked-in/in-garage
- `/admin/complete/<booking_id>`: mark checked-in booking complete
- `/export/bookings`: CSV export
- `/export/garage`: CSV export for vehicles in garage

## 6. Data Model

SQLite tables created in `models/db.py`:

- `customers`
  - `id` TEXT PK
  - `name`
  - `phone`
  - `vehicle`
- `admins`
  - `id` TEXT PK
  - `name`
  - `phone`
- `bookings`
  - `booking_id` TEXT PK
  - `customer_id`
  - `name`
  - `phone`
  - `vehicle`
  - `brand_model`
  - `service`
  - `date`
  - `status`
  - `created_at`
  - `checked_in_at`
  - `completed_at`
  - `whatsapp_sent`
  - `msg_approved_sent`
  - `msg_rejected_sent`
  - `msg_checkedin_sent`
  - `msg_completed_sent`
- `slots`
  - `date` TEXT PK
  - `total`
- `vehicles`
  - `plate_number` TEXT PK
  - `customer_id`
  - `brand`
  - `model`

Notes:

- `customers.vehicle` still exists even after vehicles were normalized into a new `vehicles` table.
- Phone uniqueness is enforced with a partial unique index on non-empty customer phone numbers.
- Admin seed rows are inserted automatically for `ADMIN001` and `ADMIN002`.

## 7. Business Rules in Code

### Auth/session

- Session uses `customer_id`, `name`, `phone`, `role`, and also a duplicated `session["user"]` object.
- Customer login can resolve by phone or customer ID.
- Admin login resolves by admin ID only.

### Booking lifecycle

Statuses are defined in `utils/constants.py`:

- `pending`
- `approved`
- `checked_in`
- `completed`
- `rejected`

Alias:

- `STATUS_IN_GARAGE = STATUS_CHECKED_IN`

Active slot statuses:

- `approved`
- `checked_in`

Lifecycle:

1. Customer creates booking -> `pending`
2. Admin approves -> `approved`
3. Admin checks in vehicle -> `checked_in` / `in garage`
4. Admin completes service -> `completed`

Rejected bookings go to `rejected`.

### Slots

- Slot totals are managed per date.
- Availability = `total - count(bookings in active statuses for that date)`.
- Customer booking creation checks slot availability before insert.
- Admin cannot reduce slot total below already booked count.

### Walk-ins

- Admin walk-in flow creates a `MANUAL####` booking.
- Manual bookings are created directly as checked-in.

## 8. Current Implementation State

The repo is not clean. `git status --short` showed modified files:

- `TODO.md`
- `logs.txt`
- `models/booking_model.py`
- `models/db.py`
- `routes/admin_routes.py`
- `services/booking_service.py`
- `utils/constants.py`

`TODO.md` indicates an in-progress/completed refactor around WhatsApp redirect-based messaging. The remaining unchecked item is manual verification of the full approve/reject/check-in/complete flow.

## 9. Known Issues and Caveats

These are the most important things another agent should know before editing:

### Active runtime issue

- `logs.txt` shows booking creation failures on 2026-04-17:
  - `DB ERROR CREATE BOOKING - BOOK1031 - 16 values for 17 columns`
  - `DB ERROR CREATE BOOKING - MANUAL1008 - 16 values for 17 columns`
- This strongly suggests a current insert/value mismatch in `models/booking_model.py` after the recent message-flag changes.

### Architecture rough edges

- `customer_routes.py` directly inserts into the `vehicles` table using `get_db()` instead of using a model/service helper.
- Phone normalization logic exists in multiple places:
  - `utils/helpers.py`
  - `services/booking_service.py`
  - `models/customer_model.py`
- This duplication increases drift risk.

### Data/bootstrap quirks

- `models.db.init_app()` calls both `init_db()` and `migrate_json_data()`, while `init_db()` also already calls `migrate_json_data()`. Because inserts use `INSERT OR IGNORE`, this is probably safe but redundant.
- The repo contains both `garage.db` at root and `data/garage.db-journal`, which suggests older or mixed DB usage/history.
- JSON files under `data/` look like legacy import sources rather than the primary source of truth now.

### Operational/security caveats

- Flask `secret_key` is hardcoded in `app.py`.
- Startup always triggers a DB backup, which is convenient but adds side effects to app boot.
- `logs.txt` is plain file logging without rotation.

### Encoding issue

- `services/booking_service.py` contains mojibake-looking WhatsApp message characters in `build_whatsapp_message()` instead of clean emoji text.

## 10. Suggested Mental Model for Future Work

If another agent needs to change behavior:

- Route/UI change: start in `routes/*` and matching `templates/*`
- Business rule change: start in `services/booking_service.py` or `services/slot_service.py`
- Persistence/schema change: start in `models/*`, especially `models/db.py`
- Session/login issue: start in `routes/auth_routes.py`, `services/auth_service.py`, `models/customer_model.py`
- Admin workflow issue: start in `routes/admin_routes.py` + `services/booking_service.py`

## 11. Recommended Next Checks for the Next Agent

1. Fix the booking insert placeholder mismatch in `models/booking_model.py`.
2. Re-test customer booking creation and admin walk-in creation.
3. Verify the WhatsApp redirect/message-flag flow end to end.
4. Consolidate phone normalization into one shared utility.
5. Consider moving vehicle insert logic out of `customer_routes.py` into service/model code.

## 12. Fast File Reading Order for a New Agent

Read these in order for the quickest orientation:

1. `app.py`
2. `models/db.py`
3. `routes/auth_routes.py`
4. `routes/customer_routes.py`
5. `routes/admin_routes.py`
6. `services/booking_service.py`
7. `models/booking_model.py`
8. `models/customer_model.py`
9. `services/slot_service.py`
10. `utils/constants.py`

