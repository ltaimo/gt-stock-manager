from datetime import datetime
from pathlib import Path
import shutil

from app.config import BASE_DIR, get_settings


def backup_sqlite() -> Path:
    settings = get_settings()
    source = BASE_DIR / "stock_manager.db"
    if not source.exists():
        raise FileNotFoundError(source)
    backup_dir = settings.outputs_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"stock_manager_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    shutil.copy2(source, target)
    return target


if __name__ == "__main__":
    print(backup_sqlite())
