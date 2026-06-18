import os
from functools import lru_cache
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


def env_path(name: str, default: Path) -> Path:
    return Path(os.getenv(name, str(default))).resolve()


class Settings:
    app_name = os.getenv("APP_NAME", "Sistema de Gestão de Stock")
    app_subtitle = os.getenv("APP_SUBTITLE", "Gestão de Terminais, SA")
    app_short_name = os.getenv("APP_SHORT_NAME", "GT Stock Manager")
    environment = os.getenv("ENVIRONMENT", "development")
    secret_key = os.getenv("SECRET_KEY", "change-me-in-production")
    reset_stock_security_code = os.getenv("RESET_STOCK_SECURITY_CODE", "")
    database_url = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'stock_manager.db'}")
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
    default_language = os.getenv("DEFAULT_LANGUAGE", "pt")

    @property
    def secure_cookies(self) -> bool:
        return os.getenv("SESSION_COOKIE_SECURE", "true" if self.environment == "production" else "false").lower() == "true"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    settings.outputs_dir.mkdir(parents=True, exist_ok=True)
    settings.documents_dir.mkdir(parents=True, exist_ok=True)
    settings.email_outbox_dir.mkdir(parents=True, exist_ok=True)
    settings.whatsapp_outbox_dir.mkdir(parents=True, exist_ok=True)
    return settings
