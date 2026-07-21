import os

from app.config import get_settings
from app.services.sync import push_snapshot_to_target


def main() -> None:
    settings = get_settings()
    target_url = os.getenv("SYNC_TARGET_URL", settings.sync_target_url)
    token = os.getenv("SYNC_TOKEN", settings.sync_token)
    timeout = int(os.getenv("SYNC_TIMEOUT_SECONDS", "45"))
    result = push_snapshot_to_target(target_url, token, timeout=timeout)
    print(f"Sincronizacao concluida: {result}")


if __name__ == "__main__":
    main()
