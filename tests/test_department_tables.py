import io
import json
import unittest
from datetime import date
from uuid import uuid4
from zipfile import ZipFile
from pypdf import PdfReader
from sqlalchemy import select
from tests import test_finance as fixture
from app.models.core import DepartmentDailyReport
from app.models.reporting import DepartmentReportTables, OperationalReport
from app.services.department_tables import parse_tables, TABLES
from app.services.operational_reporting import build_snapshot, report_presentation
from app.services.department_presentation import reports_docx, reports_pdf


class DepartmentTableTests(unittest.TestCase):
    tearDown = fixture.FinanceModuleTests.tearDown
    override_db = fixture.FinanceModuleTests.override_db
    login = fixture.FinanceModuleTests.login

    def setUp(self):
        fixture.FinanceModuleTests.setUp(self)
        self.finance_role.name = 'SuperAdmin'; self.db.commit(); self.login()
        self.url = '/operacoes-internas/relatorios-departamentais'
        self.tables = {'parade': {'note': 'Tema: prevenção', 'rows': [
            ['1', 'Vigilante teste A', 'GT', '06:30', 'Supervisor', 'Negativo', 'ABC 001'],
            ['2', 'Vigilante teste B', 'G4S', '06:30', 'Vigilante', 'Não realizado', ''],
        ]}}
        self.data = dict(department_key='security', report_date='2026-09-11', draft_key=str(uuid4()), structured_tables=json.dumps(self.tables))

    def test_draft_rows_resume_delete_and_official_exports(self):
        result = self.client.post(self.url+'/rascunho', data=self.data).json()
        self.data.update(draft_id=result['id'], draft_version=result['version'])
        restored = self.client.get(self.url+f"?department=security&draft_id={result['id']}")
        self.assertIn('Vigilante teste B', restored.text)
        self.assertIn('data-report-table="parade"', restored.text)
        self.tables['parade']['rows'].pop()
        self.data.update(structured_tables=json.dumps(self.tables), status='Submitted')
        result = self.client.post(self.url, data=self.data, headers={'Accept':'application/json'})
        self.assertEqual(result.status_code, 200, result.text)
        report_id = result.json()['id']
        official = self.db.scalar(select(OperationalReport).where(OperationalReport.source_daily_id==report_id))
        self.assertIn('Vigilante teste A', official.snapshot)
        self.assertNotIn('Vigilante teste B', official.snapshot)
        preview = self.client.get(self.url+f'/{report_id}/preview')
        self.assertIn('<th scope="col">Nome do vigilante</th>', preview.text)
        self.assertIn('<td>Vigilante teste A</td>', preview.text)
        xml = ZipFile(io.BytesIO(official.docx)).read('word/document.xml').decode()
        self.assertIn('<w:tbl>', xml); self.assertIn('Vigilante teste A', xml)
        self.assertIn('Vigilante teste A', '\n'.join(p.extract_text() for p in PdfReader(io.BytesIO(official.pdf)).pages))
        self.assertEqual(self.client.post(self.url+'/rascunho', data=self.data).status_code, 409)

    def test_week_month_and_consolidated_preserve_rows_and_snapshot(self):
        self.data['status']='Submitted'
        self.assertEqual(self.client.post(self.url,data=self.data,follow_redirects=False).status_code,303)
        for department in ['security','consolidated']:
            for period,start,end in [('weekly',date(2026,9,7),date(2026,9,13)),('monthly',date(2026,9,1),date(2026,9,30))]:
                snap=build_snapshot(self.db,department,start,end)
                row=OperationalReport(id=99,number='QA',department_key=department,period=period,date_from=start,date_to=end,version=1,status='Draft',snapshot=json.dumps(snap),supplements='{}')
                item=report_presentation(row)
                tables=[t for s in item['sections'] for t in s.get('tables',[])]
                self.assertEqual(tables[0]['rows'],self.tables['parade']['rows'])
                self.assertEqual(len(tables),1)
                self.assertTrue(reports_pdf([item],'QA','Tester').startswith(b'%PDF'))
                self.assertTrue(reports_docx([item],'QA','Tester').startswith(b'PK'))

    def test_all_department_shapes_roundtrip_and_validation(self):
        from fastapi import HTTPException
        for department,specs in TABLES.items():
            data={s['key']:{'rows':[['0']*len(s['columns'])],'note':''} for s in specs}
            self.assertEqual(parse_tables(json.dumps(data),department),data)
        for invalid in ['[]','{"unknown":{}}','{"parade":{"rows":[["short"]]}}',json.dumps({'parade':{'rows':[['x']*7]*151}})]:
            with self.assertRaises(HTTPException):parse_tables(invalid,'security')
        self.assertEqual(parse_tables('{"parade":{"rows":[["","","","","","",""]]}}','security'),{})

    def test_table_payload_cannot_cross_department_or_user(self):
        result=self.client.post(self.url+'/rascunho',data=self.data).json()
        self.data['draft_id']=result['id']
        self.login('blocked')
        self.assertEqual(self.client.post(self.url+'/rascunho',data=self.data).status_code,403)
        self.login();self.data['department_key']='maintenance'
        self.assertEqual(self.client.post(self.url+'/rascunho',data=self.data).status_code,400)
