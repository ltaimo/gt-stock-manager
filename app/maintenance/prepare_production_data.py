import argparse
from pathlib import Path

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models.core import Product, StockMovement, User
from app.seed import seed
from app.services.imports import build_import_preview, import_preview
from app.services.production_cleanup import clean_for_production


def prepare(source: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)

    seed()
    db = SessionLocal()
    try:
        actor = clean_for_production(db)
        preview = build_import_preview(db, source.name, source.read_bytes())
        if preview["errors"]:
            messages = "; ".join(item["error"] for item in preview["errors"][:5])
            raise RuntimeError(f"Importação bloqueada por {len(preview['errors'])} erro(s): {messages}")

        result = import_preview(db, preview, actor)
        db.commit()

        users = db.scalar(select(func.count()).select_from(User))
        products = db.scalar(select(func.count()).select_from(Product))
        movements = db.scalar(select(func.count()).select_from(StockMovement))
        total_stock = db.scalar(select(func.coalesce(func.sum(Product.current_stock), 0)))
        print(
            f"Preparação concluída: users={users}, products={products}, "
            f"movements={movements}, total_stock={float(total_stock)}, "
            f"imported={result.imported}, warnings={len(preview['warnings'])}"
        )
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Limpa dados operacionais e importa o stock inicial.")
    parser.add_argument("--file", required=True, type=Path, help="Ficheiro Excel com Item e Quantidade.")
    parser.add_argument("--confirm", required=True, help="Tem de ser exatamente PREPARAR-PRODUCAO.")
    args = parser.parse_args()
    if args.confirm != "PREPARAR-PRODUCAO":
        raise SystemExit("Confirmação inválida. Use --confirm PREPARAR-PRODUCAO.")
    prepare(args.file.resolve())


if __name__ == "__main__":
    main()
