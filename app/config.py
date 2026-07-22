import os
from functools import lru_cache
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
RUNTIME_DIR = BASE_DIR / ".runtime"


def env_path(name: str, default: Path) -> Path:
    return Path(os.getenv(name, str(default))).resolve()


def ensure_writable_dir(path: Path, fallback: Path) -> Path:
    try:
        path.mkdir(parents=True, exist_ok=True)
        return path
    except OSError:
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def resolve_database_url() -> str:
    value = os.getenv("DATABASE_URL")
    environment = os.getenv("ENVIRONMENT", "development")
    if value:
        return value
    if environment == "production":
        raise RuntimeError(
            "DATABASE_URL must be configured in production to avoid starting with an empty or local database."
        )
    return f"sqlite:///{BASE_DIR / 'stock_manager.db'}"


class Settings:
    app_version = os.getenv("APP_VERSION", "3.0.0")
    app_name = os.getenv("APP_NAME", "GT Integrated Management System")
    app_subtitle = os.getenv("APP_SUBTITLE", "Gestão de Terminais, SA")
    app_short_name = os.getenv("APP_SHORT_NAME", "GTIMS")
    environment = os.getenv("ENVIRONMENT", "development")
    secret_key = os.getenv("SECRET_KEY", "change-me-in-production")
    reset_stock_security_code = os.getenv("RESET_STOCK_SECURITY_CODE", "")
    database_url = resolve_database_url()
    uploads_dir = env_path("UPLOADS_DIR", BASE_DIR / "uploads")
    outputs_dir = env_path("OUTPUTS_DIR", BASE_DIR / "outputs")
    logo_path = env_path("LOGO_PATH", BASE_DIR / "app" / "static" / "img" / "logo-gt.png")
    documents_dir = env_path("DOCUMENTS_DIR", uploads_dir / "stock_documents")
    email_outbox_dir = env_path("EMAIL_OUTBOX_DIR", outputs_dir / "email_outbox")
    whatsapp_outbox_dir = env_path("WHATSAPP_OUTBOX_DIR", outputs_dir / "whatsapp_outbox")
    smtp_host = os.getenv("SMTP_HOST", "")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_password = os.getenv("SMTP_PASSWORD", "")
    smtp_from = os.getenv("SMTP_FROM", "stock@gtsa.local")
    whatsapp_webhook_url = os.getenv("WHATSAPP_WEBHOOK_URL", "")
    whatsapp_sender = os.getenv("WHATSAPP_SENDER", "+258844231830")
    default_language = os.getenv("DEFAULT_LANGUAGE", "pt")
    sync_mode = os.getenv("SYNC_MODE", "off").strip().lower()
    sync_target_url = os.getenv("SYNC_TARGET_URL", "").strip()
    sync_token = os.getenv("SYNC_TOKEN", "").strip()
    sync_interval_seconds = int(os.getenv("SYNC_INTERVAL_SECONDS", "300"))
    sync_auto_push = os.getenv("SYNC_AUTO_PUSH", "false").lower() == "true"
    mirror_read_only = os.getenv("MIRROR_READ_ONLY", "true").lower() == "true"
    session_timeout_minutes = int(os.getenv("SESSION_TIMEOUT_MINUTES", "30"))

    @property
    def session_timeout_seconds(self) -> int:
        return max(self.session_timeout_minutes, 0) * 60

    @property
    def secure_cookies(self) -> bool:
        return os.getenv("SESSION_COOKIE_SECURE", "true" if self.environment == "production" else "false").lower() == "true"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.uploads_dir = ensure_writable_dir(settings.uploads_dir, RUNTIME_DIR / "uploads")
    settings.outputs_dir = ensure_writable_dir(settings.outputs_dir, RUNTIME_DIR / "outputs")
    if not os.getenv("DOCUMENTS_DIR"):
        settings.documents_dir = settings.uploads_dir / "stock_documents"
    if not os.getenv("EMAIL_OUTBOX_DIR"):
        settings.email_outbox_dir = settings.outputs_dir / "email_outbox"
    if not os.getenv("WHATSAPP_OUTBOX_DIR"):
        settings.whatsapp_outbox_dir = settings.outputs_dir / "whatsapp_outbox"
    settings.documents_dir = ensure_writable_dir(settings.documents_dir, settings.uploads_dir / "stock_documents")
    settings.email_outbox_dir = ensure_writable_dir(settings.email_outbox_dir, settings.outputs_dir / "email_outbox")
    settings.whatsapp_outbox_dir = ensure_writable_dir(settings.whatsapp_outbox_dir, settings.outputs_dir / "whatsapp_outbox")
    return settings
