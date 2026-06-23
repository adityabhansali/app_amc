from datetime import date, datetime

from flask import Flask
from flask_login import current_user

from .config import Config
from .extensions import db, login_manager
from .utils import rupees, upload_url


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    login_manager.init_app(app)

    # Blueprints
    from .blueprints.public import public_bp
    from .blueprints.auth import auth_bp
    from .blueprints.portal import portal_bp
    from .blueprints.admin import admin_bp
    from .blueprints.chat import chat_bp

    app.register_blueprint(public_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(portal_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(chat_bp)

    # Jinja helpers
    app.jinja_env.filters["rupees"] = rupees
    app.jinja_env.filters["upload_url"] = upload_url

    @app.context_processor
    def inject_globals():
        from .models import Notification
        unread = 0
        if current_user.is_authenticated:
            unread = Notification.query.filter_by(
                user_id=current_user.id, read=False).count()
        return {
            "COMPANY_NAME": app.config["COMPANY_NAME"],
            "COMPANY_CITY": app.config["COMPANY_CITY"],
            "COMPANY_TAGLINE": app.config["COMPANY_TAGLINE"],
            "EMERGENCY_HOTLINE": app.config["EMERGENCY_HOTLINE"],
            "COMPANY_PHONE": app.config["COMPANY_PHONE"],
            "COMPANY_EMAIL": app.config["COMPANY_EMAIL"],
            "COMPANY_ADDRESS": app.config["COMPANY_ADDRESS"],
            "AI_ENABLED": Config.ai_enabled(),
            "unread_notifications": unread,
            "now": datetime.utcnow(),
            "today": date.today(),
        }

    @app.template_filter("datefmt")
    def datefmt(value, fmt="%d %b %Y"):
        if not value:
            return "—"
        return value.strftime(fmt)

    with app.app_context():
        db.create_all()

    return app
