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

    # Company branding / contact (surfaced across templates)
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

    @staticmethod
    def ai_enabled():
        key = os.getenv("OPENROUTER_API_KEY", "")
        return bool(key) and not key.startswith("PLACEHOLDER")
