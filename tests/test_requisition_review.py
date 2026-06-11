import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.models.core import RequisitionStatus
from app.services.inventory import StockError
from app.services.requisitions import issue_requisition


def make_item(item_id: int, requested: float, stock: float = 20) -> SimpleNamespace:
    product = SimpleNamespace(id=item_id, code=f"P-{item_id}", name=f"Produto {item_id}", current_stock=stock)
    return SimpleNamespace(
        id=item_id,
        product=product,
        quantity_requested=requested,
        quantity_issued=0,
        quantity_rejected=0,
        review_status="Pendente",
        review_observation=None,
        destination="Economato",
        observation=None,
    )


def make_requisition(items: list[SimpleNamespace]) -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        number="REQ-2026-00001",
        req_type="REQUISIÇÃO",
        status=RequisitionStatus.approved.value,
        items=items,
        department=SimpleNamespace(name="Economato"),
        department_id=1,
        authorization_person="Gestor de Estoque",
        requesting_user_id=2,
        issued_by_id=None,
        issued_at=None,
    )


class RequisitionReviewTests(unittest.TestCase):
    def setUp(self):
        self.actor = SimpleNamespace(id=10, role=SimpleNamespace(name="Gestor de Estoque"))
        self.db = SimpleNamespace()

    @patch("app.services.requisitions.post_movement")
    def test_partial_decision_records_approved_and_rejected_quantities(self, post_movement):
        item = make_item(1, requested=10)
        requisition = make_requisition([item])

        issue_requisition(
            self.db,
            requisition,
            self.actor,
            approved_quantities={item.id: 6},
            review_notes={item.id: "Quantidade ajustada à necessidade confirmada."},
        )

        self.assertEqual(float(item.quantity_issued), 6)
        self.assertEqual(float(item.quantity_rejected), 4)
        self.assertEqual(item.review_status, "Parcial")
        self.assertEqual(requisition.status, RequisitionStatus.partially_issued.value)
        post_movement.assert_called_once()

    @patch("app.services.requisitions.post_movement")
    def test_rejected_quantity_requires_an_item_reason(self, post_movement):
        item = make_item(1, requested=10)
        requisition = make_requisition([item])

        with self.assertRaisesRegex(StockError, "motivo da rejeição"):
            issue_requisition(
                self.db,
                requisition,
                self.actor,
                approved_quantities={item.id: 5},
                review_notes={item.id: ""},
            )

        post_movement.assert_not_called()

    @patch("app.services.requisitions.post_movement")
    def test_full_approval_does_not_require_rejection_reason(self, post_movement):
        item = make_item(1, requested=10)
        requisition = make_requisition([item])

        issue_requisition(self.db, requisition, self.actor)

        self.assertEqual(float(item.quantity_issued), 10)
        self.assertEqual(float(item.quantity_rejected), 0)
        self.assertEqual(item.review_status, "Aprovado")
        self.assertEqual(requisition.status, RequisitionStatus.issued.value)
        post_movement.assert_called_once()


if __name__ == "__main__":
    unittest.main()
