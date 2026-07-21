import argparse
import os

from app.config import get_settings
from app.services.sync import apply_snapshot, fetch_snapshot_from_target


def main() -> None:
    parser = argparse.ArgumentParser(description="Importa um snapshot remoto para a base atual.")
    parser.add_argument("--apply", action="store_true", help="Aplica o snapshot. Sem isto, apenas valida a ligacao.")
    parser.add_argument("--yes", action="store_true", help="Confirma substituicao total da base atual.")
    args = parser.parse_args()

    if args.apply and not args.yes:
        raise SystemExit("Use --apply --yes para confirmar a substituicao total da base atual.")

    settings = get_settings()
    target_url = os.getenv("SYNC_TARGET_URL", settings.sync_target_url)
    token = os.getenv("SYNC_TOKEN", settings.sync_token)
    timeout = int(os.getenv("SYNC_TIMEOUT_SECONDS", "45"))

    snapshot = fetch_snapshot_from_target(target_url, token, timeout=timeout)
    counts = {table["name"]: table.get("count", len(table.get("rows", []))) for table in snapshot.get("tables", [])}
    print(f"Snapshot recebido de {target_url}: {counts}")

    if not args.apply:
        print("Dry-run concluido. Nada foi alterado. Use --apply --yes para importar.")
        return

    applied = apply_snapshot(snapshot)
    print(f"Snapshot aplicado na base local: {applied}")


if __name__ == "__main__":
    main()
