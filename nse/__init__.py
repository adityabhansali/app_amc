from datetime import date, datetime

from flask import Flask
from flask_login import current_user

from .config import Config
from .extensions import db, login_manager, mail
from .utils import rupees, upload_url


def create_app(config_class=Config):
    import os
    app = Flask(__name__)

    # Vercel: @vercel/python only bundles .py files.  nse/_compiled.py (generated
    # by compile_templates.py) embeds all .html templates as a Python dict, so
    # it IS traced and bundled.  Use DictLoader when available.
    try:
        from jinja2 import DictLoader
        from ._compiled import TEMPLATES
        app.jinja_loader = DictLoader(TEMPLATES)
    except ImportError:
        pass  # local dev — default FileSystemLoader from Flask(__name__) is fine
    app.config.from_object(config_class)
    app.config.setdefault("SERVER_PORT", int(os.getenv("PORT", "5055")))

    db.init_app(app)
    login_manager.init_app(app)
    mail.init_app(app)

    # Blueprints
    from .blueprints.public import public_bp
    from .blueprints.auth import auth_bp
    from .blueprints.portal import portal_bp
    from .blueprints.admin import admin_bp
    from .blueprints.chat import chat_bp
    from .blueprints.sq import sq_bp

    app.register_blueprint(public_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(portal_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(sq_bp)

    # Jinja helpers
    app.jinja_env.filters["rupees"] = rupees
    app.jinja_env.filters["upload_url"] = upload_url

    @app.context_processor
    def inject_globals():
        from .models import Notification, ServiceQuotation, SupportTicket
        unread = 0
        recent_notifications = []
        sq_action_count = 0
        reminder_count = 0
        open_ticket_count = 0
        renewal_count = 0
        if current_user and current_user.is_authenticated:
            unread = Notification.query.filter_by(
                user_id=current_user.id, read=False).count()
            recent_notifications = (Notification.query
                .filter_by(user_id=current_user.id)
                .order_by(Notification.created_at.desc())
                .limit(8).all())
            # Staff-only: quotations awaiting action + open tickets + payment reminders
            if current_user.is_staff:
                pending_sq = ServiceQuotation.query.filter(
                    ServiceQuotation.status.in_(
                        ["negotiation_requested", "accepted"])).all()
                sq_action_count = sum(
                    1 for q in pending_sq
                    if q.status == "negotiation_requested"
                    or q.contract is None or q.contract.status != "active")
                try:
                    from .reminders import payment_reminder_count
                    reminder_count = payment_reminder_count()
                except Exception:
                    reminder_count = 0
                try:
                    open_ticket_count = SupportTicket.query.filter(
                        SupportTicket.status.in_(["open", "acknowledged"])).count()
                except Exception:
                    open_ticket_count = 0
                try:
                    from .reminders import renewal_reminder_count
                    renewal_count = renewal_reminder_count()
                except Exception:
                    renewal_count = 0
                # Process visit reminders + renewal/anniversary milestones
                # idempotently (fires notifications not yet sent).
                try:
                    from .reminders import process_visit_reminders, process_milestones
                    process_visit_reminders()
                    process_milestones()
                except Exception:
                    pass
        return {
            "COMPANY_NAME": app.config["COMPANY_NAME"],
            "COMPANY_CITY": app.config["COMPANY_CITY"],
            "COMPANY_TAGLINE": app.config["COMPANY_TAGLINE"],
            "EMERGENCY_HOTLINE": app.config["EMERGENCY_HOTLINE"],
            "COMPANY_PHONE": app.config["COMPANY_PHONE"],
            "COMPANY_EMAIL": app.config["COMPANY_EMAIL"],
            "COMPANY_ADDRESS": app.config["COMPANY_ADDRESS"],
            "COMPANY_UPI_ID": app.config.get("COMPANY_UPI_ID", ""),
            "AI_ENABLED": Config.ai_enabled(),
            "unread_notifications": unread,
            "recent_notifications": recent_notifications,
            "sq_action_count": sq_action_count,
            "payment_reminder_count": reminder_count,
            "open_ticket_count": open_ticket_count,
            "renewal_reminder_count": renewal_count,
            "RAZORPAY_ENABLED": Config.razorpay_enabled(),
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
