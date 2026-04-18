import glob
import os
import shutil
from datetime import datetime
from pathlib import Path

from flask import Flask

from models.db import init_app as init_db_app
from routes.admin_routes import admin_bp
from routes.auth_routes import auth_bp
from routes.customer_routes import customer_bp
from routes.main_routes import main_bp
from services.auth_service import ensure_session_user
from utils.helpers import log_action


def perform_auto_backup(app):
    """Auto-backup garage.db to backup/ folder, keep last 5 backups."""
    db_path = app.config["DATABASE"]
    if not os.path.exists(db_path):
        return

    backup_dir = Path(app.root_path) / "backup"
    backup_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    backup_filename = f"garage_backup_{timestamp}.db"
    backup_path = backup_dir / backup_filename

    try:
        shutil.copy2(db_path, backup_path)

        backups = glob.glob(str(backup_dir / "garage_backup_*.db"))
        if len(backups) > 5:
            oldest_backups = sorted(backups)[: len(backups) - 5]
            for old_backup in oldest_backups:
                os.remove(old_backup)
    except OSError as error:
        log_action("BACKUP ERROR", str(error))


def create_app():
    app = Flask(__name__)
    app.secret_key = "shreeji-auto-key-2025"
    app.config["DATABASE"] = os.path.join(app.root_path, "garage.db")

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
