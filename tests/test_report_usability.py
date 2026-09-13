import io
import json
import unittest
from datetime import date
from uuid import uuid4
from pypdf import PdfWriter
from fastapi import HTTPException
from sqlalchemy import select
from tests import test_finance as fixture
from app.models.core import DepartmentDailyReport, FinancialDailyImport
from app.models.reporting import ReportDeletion, ManagerReportSource
from app.services.report_form_schema import current_schema, schema_for_report
from app.services.operational_reporting import build_snapshot
from app.services.department_presentation import presentation, reports_pdf
from unittest.mock import patch
from pypdf import PdfReader


class ReportUsabilityTests(unittest.TestCase):
    tearDown=fixture.FinanceModuleTests.tearDown
    override_db=fixture.FinanceModuleTests.override_db
    login=fixture.FinanceModuleTests.login
    daily='/operacoes-internas/relatorios-departamentais'
    root='/operacoes-internas/relatorios'

    def setUp(self):
        fixture.FinanceModuleTests.setUp(self)
        self.finance_role.name='SuperAdmin';self.db.commit();self.login()

    def draft(self,**extra):
        data=dict(department_key='security',report_date='2026-09-12',draft_key=str(uuid4()),activities='Detalhe reservado')
        data.update(extra)
        response=self.client.post(self.daily+'/rascunho',data=data)
        self.assertEqual(response.status_code,200,response.text)
        return response.json(),data

    def test_explicit_creation_and_own_reports(self):
        row,_=self.draft()
        self.user_role.permissions=json.dumps(['internal_ops_reports_create_security']);self.db.commit()
        self.login('blocked')
        landing=self.client.get(self.daily)
        self.assertNotIn('name="report_date"',landing.text)
        self.assertNotIn('Detalhe reservado',landing.text)
        self.assertIn('name="report_date"',self.client.get(self.daily+'?create=1&department=security').text)
        self.assertEqual(self.client.get(self.daily+f'/{row["id"]}/preview').status_code,403)
        self.assertEqual(self.client.get(self.daily+f'?draft_id={row["id"]}').status_code,403)
        report=self.db.get(DepartmentDailyReport,row['id']);report.status='Submitted';self.db.commit()
        with self.assertRaises(HTTPException) as missing:
            build_snapshot(self.db,'security',date(2026,9,12),date(2026,9,12),owner_id=self.blocked_user.id)
        self.assertEqual(missing.exception.status_code,400)
        self.login();self.assertEqual(self.client.get(self.daily+f'/{row["id"]}/preview').status_code,200)

    def test_delete_permission_hides_and_restores(self):
        row,_=self.draft();url=self.root+f'/administracao/daily/{row["id"]}/apagar'
        self.login('blocked');self.assertEqual(self.client.post(url,data={'reason':'Teste'}).status_code,403)
        self.login();self.assertEqual(self.client.post(url,data={'reason':'Rascunho desnecessário'},follow_redirects=False).status_code,303)
        self.assertEqual(self.client.get(self.daily+f'/{row["id"]}/preview').status_code,404)
        self.assertNotIn('Detalhe reservado',self.client.get(self.daily).text)
        self.assertIsNotNone(self.db.get(DepartmentDailyReport,row['id']))
        deletion=self.db.scalar(select(ReportDeletion))
        self.assertEqual(self.client.post(self.root+f'/administracao/{deletion.id}/restaurar',follow_redirects=False).status_code,303)
        self.assertEqual(self.client.get(self.daily+f'/{row["id"]}/preview').status_code,200)

    def test_schema_changes_preserve_existing_drafts(self):
        row,_=self.draft()
        original=schema_for_report(self.db,'security',self.db.get(DepartmentDailyReport,row['id']))
        section=original['tables'][0]['section']
        data=dict(schema_ready='1',revision='0',shift='Diurno\nNocturno',location='Entrada\nSaída',table_0_title='Postos configurados',table_0_key='parade',table_0_section=section,col_0_0_label='Posto',col_0_0_choices='Entrada\nSaída',col_0_1_label='Observação')
        url=self.root+'/formularios/security'
        self.assertEqual(self.client.post(url,data=data,follow_redirects=False).status_code,303)
        self.assertEqual(self.client.post(url,data=data).status_code,409)
        self.db.expire_all()
        self.assertEqual(schema_for_report(self.db,'security',self.db.get(DepartmentDailyReport,row['id'])),original)
        schema=current_schema(self.db,'security');self.assertEqual(schema['tables'][0]['columns'],['Posto','Observação'])
        fresh,_=self.draft(schema_revision=schema['revision'],structured_tables=json.dumps({'parade':{'rows':[['Entrada','Verificado']],'note':''}}))
        self.assertIn('Postos configurados',self.client.get(self.daily+f'/{fresh["id"]}/preview').text)
        self.db.expire_all()
        item=presentation(self.db.get(DepartmentDailyReport,fresh['id']))
        self.assertTrue(reports_pdf([item],'Tabela configurada','Tester').startswith(b'%PDF'))
        self.login('blocked');self.assertEqual(self.client.get(url).status_code,403)

    def test_ocr_validates_pages_revision_and_preserves_original(self):
        writer=PdfWriter();writer.add_blank_page(width=600,height=800);stream=io.BytesIO();writer.write(stream);content=stream.getvalue()
        upload=self.client.post(self.root+'/gestor',data={'report_date':'2026-09-12'},files={'document':('scan.pdf',content,'application/pdf')},follow_redirects=False)
        self.assertEqual(upload.status_code,303,upload.text)
        url=upload.headers['location'];source=self.db.get(ManagerReportSource,int(url.split('/')[-1]))
        payload=dict(revision=source.revision,pages='2',text='Movimento de viaturas: 1350')
        self.assertEqual(self.client.post(url+'/ocr',data=payload).status_code,400)
        payload['pages']='1';saved=self.client.post(url+'/ocr',data=payload)
        self.assertEqual(saved.status_code,200,saved.text)
        self.assertEqual(self.client.post(url+'/ocr',data=payload).status_code,409)
        self.db.expire_all();original=self.db.get(FinancialDailyImport,source.import_id)
        self.assertEqual(original.content,content);self.assertIn('1350',original.extracted_text)
        self.assertEqual(self.db.get(ManagerReportSource,source.id).status,'Draft')
        self.login('blocked');self.assertEqual(self.client.post(url+'/ocr',data=payload).status_code,403)

    def test_copy_daily_preserves_tables_and_creates_separate_numbered_drafts(self):
        rows={'parade':{'rows':[['1','Vigilante QA','GT/SA','07:00','Vigilante','Negativo','']],'note':'Equipa'}}
        original,_=self.draft(structured_tables=json.dumps(rows))
        self.db.get(DepartmentDailyReport,original['id']).number='SEG-DR-'+'a'*32
        self.db.commit()
        copies=[]
        for suffix in ['C2','C3']:
            response=self.client.post(self.daily+f'/{original["id"]}/copiar',follow_redirects=False)
            self.assertEqual(response.status_code,303,response.text)
            page=self.client.get(response.headers['location']);self.assertIn('Vigilante QA',page.text)
            rid=int(response.headers['location'].split('draft_id=')[1]);copies.append(rid)
            self.db.expire_all();row=self.db.get(DepartmentDailyReport,rid)
            self.assertTrue(row.number.endswith(suffix));self.assertEqual(row.status,'Draft')
            self.assertLessEqual(len(row.number),40)
        self.assertNotEqual(*copies)
        self.assertNotEqual(copies[0],original['id'])
        self.login('blocked');self.assertEqual(self.client.post(self.daily+f'/{original["id"]}/copiar').status_code,403)

    def test_unified_navigation_and_quick_guide(self):
        landing=self.client.get(self.daily).text
        sidebar=landing.split('</aside>')[0]
        self.assertNotIn('Histórico de relatórios',sidebar)
        self.assertIn('Consolidar relatório',landing)
        self.assertIn('Como fazer',landing)
        self.assertNotIn('data-report-generator',self.client.get(self.root).text)
        self.assertIn('data-report-generator',self.client.get(self.root+'?create=1').text)
        guide=self.client.get(self.root+'/guia')
        self.assertEqual(guide.status_code,200)
        self.assertIn('C2, C3',guide.text)

    def test_pdf_repairs_legacy_brand_accent(self):
        from app.config import get_settings
        row,_=self.draft()
        item=presentation(self.db.get(DepartmentDailyReport,row['id']))
        with patch.object(get_settings(),'app_subtitle','Gest?o de Terminais, SA'):
            content=reports_pdf([item],'Relatório diário','Agente QA')
        text='\n'.join(page.extract_text() for page in PdfReader(io.BytesIO(content)).pages)
        self.assertIn('Gestão de Terminais, SA',text)
        self.assertNotIn('Gest?o',text)
