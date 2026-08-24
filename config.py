"""Configuration read from the environment. No secrets are hard-coded."""
import os


def _int(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _bool(name, default=False):
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


class Config:
    CLUB_NAME = os.environ.get("CLUB_NAME", "Tennis League")
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
    BASE_URL = os.environ.get("BASE_URL", "http://localhost:5000").rstrip("/")

    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///courtcall.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Windows, in hours before the session starts
    CONFIRM_HOURS_BEFORE = _int("CONFIRM_HOURS_BEFORE", 48)
    REMINDER_HOURS = _int("REMINDER_HOURS", 12)
    EXPIRE_HOURS = _int("EXPIRE_HOURS", 24)
    WAVE1_HOURS = _int("WAVE1_HOURS", 8)
    WAVE1_EXTRA = _int("WAVE1_EXTRA", 2)
    LINEUP_HOURS_BEFORE = _int("LINEUP_HOURS_BEFORE", 14)
    CUTOFF_HOURS = _int("CUTOFF_HOURS", 3)

    # Delivery
    DRY_RUN = _bool("DRY_RUN", True)
    SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "")
    FROM_EMAIL = os.environ.get("FROM_EMAIL", "noreply@example.com")
    SMS_ENABLED = _bool("SMS_ENABLED", False)
    TWILIO_SID = os.environ.get("TWILIO_SID", "")
    TWILIO_TOKEN = os.environ.get("TWILIO_TOKEN", "")
    TWILIO_FROM = os.environ.get("TWILIO_FROM", "")

    SCHEDULER_ENABLED = _bool("SCHEDULER_ENABLED", True)
    TIMEZONE = os.environ.get("TIMEZONE", "America/Chicago")
