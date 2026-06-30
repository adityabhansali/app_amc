import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-insecure-secret")

    _db_url = os.getenv("DATABASE_URL", "sqlite:///nse_amc.db")
    # Some providers (Heroku-style, older Neon URLs) hand out "postgres://",
    # which SQLAlchemy 2.0 no longer accepts — normalise to "postgresql://".
    if _db_url.startswith("postgres://"):
        _db_url = _db_url.replace("postgres://", "postgresql://", 1)
    # Resolve relative sqlite paths against the project root so the DB lives in a
    # predictable place regardless of the current working directory.
    if _db_url.startswith("sqlite:///") and not _db_url.startswith("sqlite:////"):
        _name = _db_url.replace("sqlite:///", "", 1)
        _db_url = f"sqlite:///{BASE_DIR / _name}"
    SQLALCHEMY_DATABASE_URI = _db_url
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # On serverless (Vercel) every request may hit a fresh, short-lived worker,
    # so a long-lived connection pool is a liability — connections go stale and
    # the provider's connection cap fills up. For Postgres we disable pooling
    # (NullPool: open/close per checkout) and pre-ping to drop dead sockets.
    if SQLALCHEMY_DATABASE_URI.startswith("postgresql"):
        from sqlalchemy.pool import NullPool
        SQLALCHEMY_ENGINE_OPTIONS = {
            "poolclass": NullPool,
            "pool_pre_ping": True,
        }

    UPLOAD_FOLDER = BASE_DIR / "nse" / "static" / "uploads"
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB per upload
    ALLOWED_IMAGE_EXT = {"png", "jpg", "jpeg", "gif", "webp"}
    ALLOWED_DOC_EXT = {"pdf", "png", "jpg", "jpeg"}

    # OpenRouter
    OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
    OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "anthropic/claude-haiku-4.5")
    OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

    # Vercel Blob — when set (production on Vercel), uploads go to Blob storage
    # instead of the local, ephemeral filesystem. Unset locally => disk uploads.
    BLOB_READ_WRITE_TOKEN = os.getenv("BLOB_READ_WRITE_TOKEN", "")

    # ── Email (Flask-Mail via Microsoft Outlook / Office 365) ──────────────────
    # Add MAIL_PASSWORD=<your-password> to .env to enable sending.
    # All other values are set to the correct Outlook SMTP defaults below.
    MAIL_SERVER   = os.getenv("MAIL_SERVER",   "smtp.office365.com")
    MAIL_PORT     = int(os.getenv("MAIL_PORT", "587"))
    MAIL_USE_TLS  = True
    MAIL_USE_SSL  = False
    MAIL_USERNAME = os.getenv("MAIL_USERNAME", "assistantoperations@northernstarengineering.com")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "")
    MAIL_DEFAULT_SENDER = (
        os.getenv("MAIL_SENDER_NAME", "Northern Star Engineering"),
        os.getenv("MAIL_USERNAME", "assistantoperations@northernstarengineering.com"),
    )
    # Set to False to suppress actual sends during development (log to console instead)
    MAIL_SUPPRESS_SEND = os.getenv("MAIL_SUPPRESS_SEND", "true").lower() == "true"

    # Business-specific constants (used in quotation PDFs and emails)
    COMPANY_GST = os.getenv("COMPANY_GST", "24ALQPD0899P1ZD")
    SALES_MANAGER_PHONE = os.getenv("SALES_MANAGER_PHONE", "+919687266625")

    # ── Company branding / contact (surfaced across templates) ──────────────────
    COMPANY_NAME = os.getenv("COMPANY_NAME", "Northern Star Engineering")
    COMPANY_CITY = os.getenv("COMPANY_CITY", "Surat, Gujarat")
    COMPANY_TAGLINE = os.getenv(
        "COMPANY_TAGLINE",
        "Protecting Lives, Securing Futures — Your Trusted Fire Safety Partner")
    EMERGENCY_HOTLINE = os.getenv("EMERGENCY_HOTLINE", "1800-891-8565")
    COMPANY_PHONE = os.getenv("COMPANY_PHONE", "9687266625")
    COMPANY_EMAIL = os.getenv("COMPANY_EMAIL", "info@northernstarengineering.com")
    COMPANY_ADDRESS = os.getenv(
        "COMPANY_ADDRESS",
        "521-522, Western Business Park, opp. S.D. Jain School, Surat, Gujarat 395007")

    # UPI VPA (Virtual Payment Address) the customer pays into when they tap
    # "Pay by UPI / GPay" on a quotation link. Set COMPANY_UPI_ID in .env to the
    # firm's real UPI handle (e.g. "northernstar@okhdfcbank"). Until set, the UPI
    # button shows a "not configured" notice instead of a live QR.
    COMPANY_UPI_ID   = os.getenv("COMPANY_UPI_ID", "")
    COMPANY_UPI_NAME = os.getenv("COMPANY_UPI_NAME", COMPANY_NAME)

    # Public base URL used when building shareable links (quotation WhatsApp links,
    # email links, etc.) that must be clickable on a client's phone.
    # Options:
    #   • Same WiFi  → http://192.168.X.X:5055   (auto-detected if left blank, dev only)
    #   • ngrok      → https://xxxx.ngrok-free.app
    #   • Vercel     → https://your-app.vercel.app
    # Leave blank in dev — the app will use the Mac's LAN IP automatically.
    BASE_URL = os.getenv("BASE_URL", "").rstrip("/")

    @staticmethod
    def ai_enabled():
        key = os.getenv("OPENROUTER_API_KEY", "")
        return bool(key) and not key.startswith("PLACEHOLDER")
