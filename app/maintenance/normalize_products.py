from __future__ import annotations

import re
from collections import defaultdict

from sqlalchemy import select

from app.database import SessionLocal
from app.models.core import AuditLog, Product, RequisitionItem, StockDocumentProduct, StockMovement, User
from app.services.inventory import merge_product_warehouse_stock, recalculate_product_stock
from app.services.transactions import atomic


NAME_OVERRIDES = {
    "COMPUTADORES (PC)": "Computadores (PC)",
    "MONITORES": "Monitores",
    "Lamapada OSRAM 7watts": "Lâmpada OSRAM 7W",
    "Electrobomba Pedrolo": "Eletrobomba Pedrollo",
    "Caixa de grafos Normais": "Caixa de agrafos normais",
    "Embalagens de Plastico de lixo": "Embalagens de plástico para lixo",
    "Danger tipe": "Danger Tape",
    "Oculos de proteção": "Óculos de proteção",
    "Borrachas p/ carimbo": "Borrachas para carimbo",
    "Canetas azuis": "Canetas azuis",
    "canetas vermelhas": "Canetas vermelhas",
    "Bomba de agua": "Bomba de água",
    "Blade de tinta 5L": "Balde de tinta 5L",
    "Bicha Flexivel": "Bicha flexível",
    "Anti caleiras ( Perneiras )": "Anti-caleiras (perneiras)",
    "Maquina de Lavar a alta pressao": "Máquina de lavar de alta pressão",
    "Canhoes": "Canhões",
    "Plasticos De fita Teflon": "Plásticos de fita Teflon",
    "Maquina de corte de capim": "Máquina de corte de capim",
    "Livros p/ Ticket Manual (Guarita de entrada)": "Livros para ticket manual (guarita de entrada)",
    "Lixivia (Javel)": "Lixívia (Javel)",
    "Mascaras": "Máscaras",
    "Mope": "Mop",
    "Torneiras de Lavatorio": "Torneiras de lavatório",
    "Rolos de fio de Relva": "Rolos de fio de relva",
    "Caixa de rolos para POS": "Caixa de rolos para POS",
    "Povim": "Pó Vim",
    "Lampadas Florescente 36watts": "Lâmpadas fluorescentes 36W",
    "Rolos Papel aderente": "Rolos de papel aderente",
    "Sabão p/ mão (garrafas)": "Sabão para mãos (garrafas)",
    "Sabão para loiça (5L)": "Sabão para loiça 5L",
    "Armadura Requa 36Watts": "Armadura régua 36W",
    "Tinta p/ carimbo": "Tinta para carimbo",
    "T ips 3/4": "T IPS 3/4",
    "Uniao Especial": "União especial",
    "Fio PBC": "Fio PBC",
    "T PVC": "T PVC",
    "PVC Electrical tape": "Fita isoladora PVC",
    "flash": "Flash drive",
    "toner 59A": "Toner 59A",
    "Lampaddas ledes para segurancas": "Lâmpadas LED para seguranças",
    "pecas de motobomba": "Peças de motobomba",
    "1a embalagem de Omo 6x600g": "Embalagem de OMO 6x600g",
    "Keyboard HP K200 – English": "Teclado HP K200 - English",
    "Impressora POS Epson Termica TM-T20III (Serial + USB)": "Impressora POS Epson térmica TM-T20III (Serial + USB)",
    "CZUR Lens 1200 Pro A4 PORTABLE SCANNER 12 megapixels Resolution 4032 x 3024, Interface USB Type -C": "Scanner portátil CZUR Lens 1200 Pro A4 12MP USB-C",
}


def infer_unit(name: str) -> str:
    text = name.casefold()
    if "papel a4" in text:
        return "resma" if "caixa" not in text else "caixa"
    if any(word in text for word in ["caixa", "conjunto"]):
        return "caixa"
    if any(word in text for word in ["embalagem", "embalagens", "sacos de lixo"]):
        return "embalagem"
    if any(word in text for word in ["rolo", "rolos", "fita-cola", "fita isoladora", "danger tape"]):
        return "rolo"
    if any(word in text for word in ["luvas", "óculos", "oculos", "perneiras"]):
        return "par"
    if "garrafa" in text:
        return "garrafa"
    if re.search(r"\b\d+\s*l\b", text) or "5l" in text or "1000l" in text:
        return "L"
    if re.search(r"\b\d+\s*g\b", text) or "600g" in text:
        return "g"
    if "detergente em pó" in text or "omo" in text:
        return "kg"
    if re.search(r"\b\d+\s*m\b", text) or "100m" in text:
        return "m"
    if any(word in text for word in ["tubo", "fio"]):
        return "m"
    if any(word in text for word in ["detergente", "lixívia", "lixivia", "álcool", "alcool", "sabão", "pesticida"]):
        return "L"
    return "un"


def consolidate_exact_duplicate_products(db) -> int:
    products = db.scalars(select(Product).where(Product.status == "active").order_by(Product.code, Product.id)).all()
    groups: dict[tuple[str, str, int | None], list[Product]] = defaultdict(list)
    for product in products:
        normalized_name = " ".join((product.name or "").casefold().split())
        normalized_unit = (product.unit or "").strip().casefold()
        if normalized_name:
            groups[(normalized_name, normalized_unit, product.category_id)].append(product)

    consolidated = 0
    for group in groups.values():
        if len(group) <= 1:
            continue
        canonical = sorted(group, key=lambda product: (product.code or "", product.id))[0]
        duplicates = [product for product in group if product.id != canonical.id]
        for duplicate in duplicates:
            for movement in db.scalars(select(StockMovement).where(StockMovement.product_id == duplicate.id)).all():
                movement.product_id = canonical.id
            for requisition_item in db.scalars(select(RequisitionItem).where(RequisitionItem.product_id == duplicate.id)).all():
                requisition_item.product_id = canonical.id
            for document_link in db.scalars(select(StockDocumentProduct).where(StockDocumentProduct.product_id == duplicate.id)).all():
                existing_link = db.scalar(
                    select(StockDocumentProduct).where(
                        StockDocumentProduct.document_id == document_link.document_id,
                        StockDocumentProduct.product_id == canonical.id,
                    )
                )
                if existing_link:
                    db.delete(document_link)
                else:
                    document_link.product_id = canonical.id
            merge_product_warehouse_stock(db, source=duplicate, target=canonical)
            db.flush()
            db.delete(duplicate)
            consolidated += 1
        db.flush()
        recalculate_product_stock(db, canonical)
    return consolidated


def normalize_products() -> None:
    with SessionLocal() as db:
        actor = db.scalar(select(User).where(User.username == "superadmin"))
        changes = []
        with atomic(db):
            products = db.scalars(select(Product).order_by(Product.code)).all()
            for product in products:
                old = {"name": product.name, "unit": product.unit}
                new_name = NAME_OVERRIDES.get(product.name, " ".join(product.name.split()))
                new_unit = infer_unit(new_name)
                if product.name != new_name or product.unit != new_unit:
                    product.name = new_name
                    product.unit = new_unit
                    changes.append({"code": product.code, "old": old, "new": {"name": new_name, "unit": new_unit}})
            if actor and changes:
                db.add(
                    AuditLog(
                        user_id=actor.id,
                        action="Normalizou nomenclatura e unidades de produtos",
                        module="Produtos",
                        record_id="bulk-normalize",
                        new_value={"updated": len(changes), "sample": changes[:20]}.__repr__(),
                    )
                )
            consolidated = consolidate_exact_duplicate_products(db)
            if actor and consolidated:
                db.add(
                    AuditLog(
                        user_id=actor.id,
                        action="Consolidou produtos duplicados exatos",
                        module="Produtos",
                        record_id="bulk-consolidate-duplicates",
                        new_value={"consolidated": consolidated}.__repr__(),
                    )
                )
        print(f"Produtos atualizados: {len(changes)}")
        print(f"Duplicados exatos consolidados: {consolidated}")
        for item in changes[:30]:
            print(f"{item['code']}: {item['old']['name']} -> {item['new']['name']} [{item['new']['unit']}]")


if __name__ == "__main__":
    normalize_products()
