import os

from flask import Flask

from models.db import init_app as init_db_app
from routes.admin_routes import admin_bp
from routes.auth_routes import auth_bp
from routes.customer_routes import customer_bp
from routes.main_routes import main_bp
from services.auth_service import ensure_session_user


def create_app():
    app = Flask(__name__)
    app.secret_key = "shreeji-auto-key-2025"
    app.config["DATABASE"] = os.path.join(app.root_path, "garage.db")

    init_db_app(app)

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
    app.run(debug=True)
