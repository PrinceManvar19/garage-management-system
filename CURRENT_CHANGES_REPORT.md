# Current Changes Report

Date: 2026-04-18

This report summarizes the current worktree changes for the files you listed. Some names below are normalized to the real repo paths:

- `booking-model.py` -> `models/booking_model.py`
- `customer-model.py` -> `models/customer_model.py`
- `db.py` -> `models/db.py`
- `admin-rountes.py` -> `routes/admin_routes.py`
- `bookinf-service.py` -> `services/booking_service.py`
- `customer-routes.py` -> `routes/customer_routes.py`
- `admin-base.html` -> `templates/admin_base.html`
- `admin-walkin.html` -> `templates/admin_walkin.html`
- `checkin.html` -> `templates/checkin.html`
- `constants.py` -> `utils/constants.py`
- `garage-smoke-test.db-journal` -> `garage_smoke_test.db-journal`
- `auth-test-tmp.db-journal` -> `data/auth_test_tmp.db-journal`

## Snapshot

- Modified tracked files in scope: 12
- Untracked files in scope: 2 journal files
- Existing broad project report also present: `AI_AGENT_PROJECT_REPORT.md`

## File-by-File Changes

### `app.py`

- Added SQLite-aware database discovery and scoring logic.
- App now resolves the active database path dynamically instead of always using repo-root `garage.db`.
- Startup can restore the best database candidate from legacy/default/backup locations.
- Backup behavior was hardened:
  - skips when DB does not exist
  - stores backups under the active DB directory
  - handles copy/delete failures more safely

### `garage_smoke_test.db-journal`

- Untracked SQLite journal file.
- Runtime/test artifact, not application source code.
- Current size: 512 bytes.
- Last modified: 2026-04-17 22:16:39.

### `logs.txt`

- App log contains new entries from 2026-04-17.
- It records:
  - booking completion events
  - earlier insert failures with `16 values for 17 columns`
  - later successful smoke/manual booking activity
- This file reflects runtime history, not direct code logic changes.

### `data/auth_test_tmp.db-journal`

- Untracked SQLite journal file under `data/`.
- Likely created by auth/test database activity.
- Current size: 512 bytes.
- Last modified: 2026-04-17 22:16:56.

### `models/booking_model.py`

- Booking column list expanded with four message-tracking flags:
  - `msg_approved_sent`
  - `msg_rejected_sent`
  - `msg_checkedin_sent`
  - `msg_completed_sent`
- Row normalization now returns those flags as integers.
- Booking insert statement was expanded to write the new columns.
- `update_booking_status()` now supports optional dynamic message-flag updates.
- Added `update_message_flags()` helper for updating only selected notification fields.

### `models/customer_model.py`

- Customer search became case-insensitive for ID/vehicle matching.
- Phone searching now uses normalized digits before building the query.
- Search SQL was tightened so phone matching only runs when a normalized phone term exists.

### `models/db.py`

- Booking schema now includes the four new message-tracking columns.
- Booking migration adds missing message columns for existing databases.
- Migration also backfills notification flags based on current booking status.
- Rejected-flag cleanup was added for non-rejected rows.

### `routes/admin_routes.py`

- WhatsApp message generation/redirect flow was centralized through a shared helper.
- Admin actions now try to update notification flags before redirecting to WhatsApp.
- Approval, rejection, check-in, and completion flows were adjusted to use the new notification flow.
- Added or retained cleaner JSON admin endpoints for:
  - customer search
  - customer creation
- Added explicit `/checkin` and `/admin/checkin` page routes for the check-in screen.
- A large amount of older/duplicate route logic was removed from this file as part of the cleanup/refactor.

### `services/booking_service.py`

- Service layer now initializes all new message-tracking fields when creating bookings.
- Manual walk-in creation now uses `STATUS_CHECKED_IN`.
- Added `build_whatsapp_message()` to compose status-based customer notifications.
- Removed the older `mark_whatsapp_sent()` flow in favor of per-message flags.
- Error handling/logging was cleaned up in booking and walk-in creation paths.

### `routes/customer_routes.py`

- Removed debug `print()` statements from vehicle-add flow.
- Vehicle insert path now handles `sqlite3.IntegrityError` explicitly.
- Duplicate vehicle attempts now return a clean `409` response after rollback.
- General DB-error path still returns a `500`, but without console debug noise.

### `templates/admin_base.html`

- Sidebar Check-In link now points to `url_for('admin.admin_checkin_page')`.
- Active-state logic was updated so both `/checkin` and `/admin/checkin` highlight the menu item.

### `templates/admin_walkin.html`

- Removed a stray browser `console.log()` from the vehicle select script.

### `templates/checkin.html`

- Template status checks were updated from `'in_garage'` to `'checked_in'`.
- The check-in page now renders the in-garage/completion state using the renamed status value.

### `utils/constants.py`

- Introduced `STATUS_CHECKED_IN = "checked_in"`.
- Kept `STATUS_IN_GARAGE` as a legacy alias to preserve compatibility.
- Active slot statuses now use `STATUS_CHECKED_IN` instead of the old literal/status constant.

## Main Theme of the Current Changes

The current work is mainly a booking-status and notification refactor:

- rename the garage status from `in_garage` to `checked_in`
- track each WhatsApp notification type separately
- move WhatsApp redirect/message logic into shared service/route helpers
- improve admin check-in/walk-in flow structure
- make database resolution and backup handling safer

## Notes

- The two `*.db-journal` files are temporary SQLite artifacts, not feature code.
- `logs.txt` still shows earlier insert-count errors, which look like historical traces from before the booking insert was expanded to match the new schema.
