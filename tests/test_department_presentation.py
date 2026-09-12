import io
import unittest
from zipfile import ZipFile

from sqlalchemy import select
from pypdf import PdfReader

from tests import test_finance as finance_fixture
from app.models.core import DepartmentDailyReport


class DepartmentPresentationTests(unittest.TestCase):
    tearDown = finance_fixture.FinanceModuleTests.tearDown
    override_db = finance_fixture.FinanceModuleTests.override_db
    login = finance_fixture.FinanceModuleTests.login
    # Reuse the isolated database and authenticated client, not Finance tests.
    def setUp(self):
        finance_fixture.FinanceModuleTests.setUp(self)
        self.finance_role.name = "SuperAdmin"
        self.db.commit()
        self.login()

    def test_structured_entry_preview_exports_and_access(self):
        response = self.client.post('/operacoes-internas/relatorios-departamentais', data={
            'department_key': 'security', 'report_date': '2026-08-31',
            'incidents': 'Incidente <teste> & acompanhamento',
            'equipment_status__0': 'Nenhuma entrada.', 'team__0': 'Equipa completa.',
            'notes': 'Nota final preservada', 'activities__2': '08h00 — ronda concluída',
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        report = self.db.scalar(select(DepartmentDailyReport))
        self.assertIn('Entrada de mercadorias apreendidas:', report.equipment_status)
        url = f'/operacoes-internas/relatorios-departamentais/{report.id}/preview'
        preview = self.client.get(url)
        self.assertEqual(preview.status_code, 200)
        self.assertIn('&lt;teste&gt;', preview.text)
        self.assertIn('Nota final preservada', preview.text)
        self.assertIn('logo-gt.png', preview.text)
        for base in [url, '/relatorios/operacoes-internas/departamentos?date_from=2026-08-31&date_to=2026-08-31']:
            sep = '&' if '?' in base else '?'
            pdf = self.client.get(base+sep+'export=pdf')
            self.assertEqual(pdf.status_code, 200)
            text = '\n'.join(p.extract_text() for p in PdfReader(io.BytesIO(pdf.content)).pages)
            self.assertIn('Nota final preservada', text)
            self.assertIn('Equipa completa.', text)
            word = self.client.get(base+sep+'export=docx')
            self.assertEqual(word.status_code, 200)
            with ZipFile(io.BytesIO(word.content)) as z:
                self.assertIn('Nota final preservada', z.read('word/document.xml').decode())
                self.assertTrue(any(n.startswith('word/media/') for n in z.namelist()))
        self.login('blocked')
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_legacy_text_and_long_export(self):
        response = self.client.post('/operacoes-internas/relatorios-departamentais', data={
            'department_key': 'maintenance', 'report_date': '2026-08-31',
            'activities': '\n'.join(f'Trabalho {i}: verificação e reparação concluída.' for i in range(160)),
            'team': 'Equipa antiga', 'notes': 'ÚLTIMA NOTA',
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        report = self.db.scalar(select(DepartmentDailyReport))
        pdf = self.client.get(f'/operacoes-internas/relatorios-departamentais/{report.id}/preview?export=pdf')
        pages = PdfReader(io.BytesIO(pdf.content)).pages
        self.assertGreater(len(pages), 2)
        self.assertIn('ÚLTIMA NOTA', '\n'.join(p.extract_text() for p in pages))
