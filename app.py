import os
import shutil
import glob
import sqlite3
from datetime import datetime

from flask import Flask

from models.db import init_app as init_db_app
from routes.admin_routes import admin_bp
from routes.auth_routes import auth_bp
from routes.customer_routes import customer_bp
from routes.main_routes import main_bp
from services.auth_service import ensure_session_user


def _default_data_dir(app):
    configured_db = os.environ.get("GARAGE_DATABASE", "").strip()
    if configured_db:
        return os.path.dirname(os.path.abspath(configured_db))

    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        return os.path.join(local_app_data, "GarageManagement")
    return os.path.join(app.root_path, "data")


def _database_score(path):
    if not path or not os.path.exists(path) or os.path.getsize(path) <= 0:
        return -1

    try:
        connection = sqlite3.connect(path)
        cursor = connection.cursor()
        total = 0
        for table in ("customers", "bookings", "slots", "admins"):
            try:
                total += int(cursor.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            except sqlite3.Error:
                return -1
        connection.close()
        return total
    except sqlite3.Error:
        return -1


def _best_database_source(app, target_db_path):
    candidates = []
    legacy_db_path = os.path.join(app.root_path, "garage.db")
    data_db_path = os.path.join(app.root_path, "data", "garage.db")

    for candidate in (legacy_db_path, data_db_path):
        if os.path.abspath(candidate) != os.path.abspath(target_db_path):
            candidates.append(candidate)

    candidates.extend(sorted(glob.glob(os.path.join(app.root_path, "backup", "*.db")), reverse=True))

    best_path = None
    best_score = -1
    for candidate in candidates:
        score = _database_score(candidate)
        if score > best_score:
            best_path = candidate
            best_score = score
    return best_path, best_score


def resolve_database_path(app):
    configured_db = os.environ.get("GARAGE_DATABASE", "").strip()
    if configured_db:
        data_dir = os.path.dirname(os.path.abspath(configured_db))
        if data_dir:
            os.makedirs(data_dir, exist_ok=True)
        return os.path.abspath(configured_db)

    data_dir = _default_data_dir(app)
    os.makedirs(data_dir, exist_ok=True)

    db_path = os.path.join(data_dir, "garage.db")
    current_score = _database_score(db_path)
    best_source_path, best_source_score = _best_database_source(app, db_path)

    if best_source_path and best_source_score > current_score:
        try:
            shutil.copy2(best_source_path, db_path)
            print(f"Database restored from: {best_source_path}")
        except OSError as error:
            print(f"Database restore skipped: {error}")
    return db_path


def perform_auto_backup(app):
    """Auto-backup garage.db to backup/ folder, keep last 5 backups."""
    db_path = app.config["DATABASE"]
    if not os.path.exists(db_path):
        return

    backup_dir = os.path.join(os.path.dirname(db_path), "backup")
    os.makedirs(backup_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    backup_filename = f"garage_backup_{timestamp}.db"
    backup_path = os.path.join(backup_dir, backup_filename)

    try:
        shutil.copy2(db_path, backup_path)
    except OSError as error:
        print(f"Backup skipped: {error}")
        return

    # Keep only last 5 backups
    backups = sorted(glob.glob(os.path.join(backup_dir, "garage_backup_*.db")))
    if len(backups) > 5:
        oldest_backups = backups[: len(backups) - 5]
        for old_backup in oldest_backups:
            try:
                os.remove(old_backup)
            except OSError:
                pass
    print(f"Backup created: {backup_filename}")


def create_app():
    app = Flask(__name__)
    app.secret_key = "shreeji-auto-key-2025"
    app.config["DATABASE"] = resolve_database_path(app)

    init_db_app(app)
    
    perform_auto_backup(app)

    @app.before_request
    def sync_session_user():
        ensure_session_user()

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(customer_bp)
    app.register_blueprint(admin_bp)
    return app


app = create_app()


if __name__ == "__main__":
    app.config['TEMPLATES_AUTO_RELOAD'] = True
    app.run(host="0.0.0.0", port=5000, debug=True)
