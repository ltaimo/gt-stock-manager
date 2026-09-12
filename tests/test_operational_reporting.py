import io
import json
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4
from sqlalchemy import select
from app.models.core import DepartmentDailyReport, FinancialDailyImport, Role, User, Notification
from app.models.reporting import OperationalReport, ManagerReportSource, DailyReportEntry, OperationalReportSettings, CctvCamera, CctvStatusLog, CctvSchedule, OperationalPending
from app.services.reporting_common import utc_day
from app.services.operational_reporting import aggregate_metrics, build_snapshot
from app.services.cctv import cctv_snapshot, create_pending
from tests import test_finance as finance_fixture
from tests.test_finance import docx_bytes


class OperationalReportingTests(unittest.TestCase):
    tearDown=finance_fixture.FinanceModuleTests.tearDown
    override_db=finance_fixture.FinanceModuleTests.override_db
    login=finance_fixture.FinanceModuleTests.login
    root='/operacoes-internas/relatorios'
    headers={'Accept':'application/json'}

    def setUp(self):
        finance_fixture.FinanceModuleTests.setUp(self)
        self.finance_role.name='SuperAdmin';self.db.commit();self.login()

    def seed_daily(self,day,department='security',value=None,metric='vehicles_in',dimension='Importações'):
        row=DepartmentDailyReport(number=str(uuid4()),department_key=department,report_date=utc_day(day),activities='Inspeção sem avarias.',status='Submitted',created_by_id=self.finance_user.id)
        self.db.add(row);self.db.flush()
        if value is not None:self.db.add(DailyReportEntry(report_id=row.id,category='metric',title='Indicador diário',metric_key=metric,dimension=dimension,value=value))
        self.db.commit();return row

    def manager(self,day,values=()):
        response=self.client.post(self.root+'/gestor',data={'report_date':str(day)},files={'document':('gestor.docx',docx_bytes('Relatório operacional '+str(day)+' '+str(uuid4())),'application/vnd.openxmlformats-officedocument.wordprocessingml.document')},follow_redirects=False)
        self.assertEqual(response.status_code,303,response.text)
        source_id=int(response.headers['location'].split('/')[-1]);row=self.db.get(ManagerReportSource,source_id)
        data={'revision':row.revision,'action':'review','notes':'Original revisto; departamentos obtidos diretamente da aplicação.'}
        for i,(key,dimension,value) in enumerate(values):data.update({f'metric_{i}_key':key,f'metric_{i}_dimension':dimension,f'metric_{i}_value':str(value)})
        result=self.client.post(self.root+f'/gestor/{source_id}',data=data,headers=self.headers)
        self.assertEqual(result.status_code,200,result.text)
        return source_id

    def generate(self,department,period,day):
        response=self.client.post(self.root+'/gerar',data={'department':department,'period':period,'anchor':str(day)},follow_redirects=False)
        self.assertEqual(response.status_code,303,response.text)
        return int(response.headers['location'].split('/')[-1])

    def submit(self,report_id,**extra):
        self.db.expire_all();row=self.db.get(OperationalReport,report_id)
        return self.client.post(self.root+f'/{report_id}/guardar',data={'revision':row.revision,'action':'Submitted',**extra},headers=self.headers)

    def test_daily_manager_consolidated_archive_and_notifications(self):
        day=date(2026,9,2)
        for department in ['security','maintenance','it']:self.seed_daily(day,department)
        self.manager(day,[('vehicles_total','Geral',1350),('revenue','Geral','2.932.293,40')])
        receiver=Role(name='Chefias de teste',permissions='["operational_reports_receive"]');self.db.add(receiver);self.db.flush()
        self.blocked_user.role_id=receiver.id;self.db.commit()
        report_id=self.generate('consolidated','daily',day)
        page=self.client.get(self.root+f'/{report_id}');self.assertEqual(page.status_code,200);self.assertIn('1350',page.text)
        result=self.submit(report_id,summary='Movimento do terminal revisto.',conclusion='Acompanhamento regular.')
        self.assertEqual(result.status_code,200,result.text)
        pdf=self.client.get(self.root+f'/{report_id}/ficheiro/pdf');word=self.client.get(self.root+f'/{report_id}/ficheiro/docx')
        self.assertTrue(pdf.content.startswith(b'%PDF'));self.assertTrue(word.content.startswith(b'PK'))
        self.db.expire_all();row=self.db.get(OperationalReport,report_id)
        self.assertEqual(pdf.content,row.pdf);self.assertEqual(word.content,row.docx)
        notice=self.db.scalar(select(Notification).where(Notification.user_id==self.blocked_user.id,Notification.module=='RelatoriosOperacionais'))
        self.assertIsNotNone(notice)
        self.login('blocked');opened=self.client.get(f'/notificacoes/{notice.id}/abrir',follow_redirects=False)
        self.assertEqual(opened.headers['location'],self.root+f'/{report_id}')
        self.assertEqual(self.client.get(self.root+f'/{report_id}').status_code,200)
        self.assertEqual(self.client.post(self.root+'/gerar',data={'department':'consolidated','period':'monthly','anchor':str(day)}).status_code,403)

    def test_missing_sources_are_visible_and_block_submission(self):
        day=date(2026,9,3);self.seed_daily(day)
        report_id=self.generate('consolidated','daily',day)
        self.assertIn('Fontes incompletas',self.client.get(self.root+f'/{report_id}').text)
        self.assertEqual(self.submit(report_id,review_notes='Justificação sem autorização').status_code,409)
        self.db.add(OperationalReportSettings(id=1,allow_partial=True,week_start=0));self.db.commit()
        self.assertEqual(self.submit(report_id).status_code,409)
        self.assertEqual(self.submit(report_id,review_notes='Envio parcial autorizado; Manutenção e IT por entregar.').status_code,200)

    def test_weekly_monthly_use_daily_sources_and_meter_differences(self):
        for day,value in [(date(2026,9,1),20),(date(2026,9,7),30)]:
            report=self.seed_daily(day,value=value)
            self.db.add(DailyReportEntry(report_id=report.id,category='energy',title='Leitura EDM',metric_key='meter_kwh',dimension='EDM',value=100 if value==20 else 160));self.db.commit()
        weekly=self.generate('security','weekly',date(2026,9,2));self.db.expire_all()
        snapshot=json.loads(self.db.get(OperationalReport,weekly).snapshot)
        self.assertEqual(next(m for m in snapshot['metrics'] if m['key']=='vehicles_in')['value'],'20.0000')
        monthly=self.generate('security','monthly',date(2026,9,2));self.db.expire_all();monthly_row=self.db.get(OperationalReport,monthly)
        snapshot=json.loads(monthly_row.snapshot)
        self.assertEqual(next(m for m in snapshot['metrics'] if m['key']=='vehicles_in')['value'],'50.0000')
        meter=next(m for m in snapshot['metrics'] if m['key']=='meter_kwh')
        self.assertEqual(meter['value'],'160.0000');self.assertEqual(meter['delta'],'60.0000')
        saved=self.client.post(self.root+f'/{monthly}/guardar',data={'revision':monthly_row.revision,'action':'In Review','summary':'Resumo complementado.'},headers=self.headers)
        self.assertEqual(saved.status_code,200,saved.text)
        self.assertIn('Resumo complementado.',self.client.get(self.root+f'/{monthly}').text)
        for period in ['weekly','monthly']:
            report_id=self.generate('consolidated',period,date(2026,9,2))
            self.assertEqual(self.client.get(self.root+f'/{report_id}').status_code,200)

    def test_versions_preserve_official_bytes_and_reject_stale_edits(self):
        day=date(2026,9,4)
        for key in ['security','maintenance','it']:self.seed_daily(day,key)
        self.manager(day)
        report_id=self.generate('consolidated','daily',day);row=self.db.get(OperationalReport,report_id);revision=row.revision
        save=self.client.post(self.root+f'/{report_id}/guardar',data={'revision':revision,'action':'Draft','summary':'Primeiro complemento'},headers=self.headers)
        self.assertEqual(save.status_code,200)
        stale=self.client.post(self.root+f'/{report_id}/guardar',data={'revision':revision,'action':'Draft','summary':'Cópia desatualizada'},headers=self.headers)
        self.assertEqual(stale.status_code,409)
        self.assertEqual(self.submit(report_id).status_code,200)
        old=self.client.get(self.root+f'/{report_id}/ficheiro/pdf').content
        self.assertEqual(self.client.post(self.root+f'/{report_id}/regenerar',data={'revision':1}).status_code,409)
        new=self.client.post(self.root+f'/{report_id}/versao',follow_redirects=False);self.assertEqual(new.status_code,303)
        new_id=int(new.headers['location'].split('/')[-1]);self.assertNotEqual(new_id,report_id)
        self.assertEqual(self.client.get(self.root+f'/{report_id}/ficheiro/pdf').content,old)
        self.assertEqual(self.client.post(self.root+f'/{report_id}/versao').status_code,409)

    def test_export_failure_preserves_draft(self):
        self.seed_daily(date(2026,9,1));report_id=self.generate('security','weekly',date(2026,9,1))
        self.db.add(OperationalReportSettings(id=1,allow_partial=True));self.db.commit()
        with patch('app.services.operational_reporting.reports_docx',side_effect=RuntimeError('test renderer failure')):
            response=self.submit(report_id,review_notes='Parcial autorizado.')
            self.assertEqual(response.status_code,500)
        self.db.expire_all();row=self.db.get(OperationalReport,report_id)
        self.assertEqual(row.status,'Generated');self.assertIsNone(row.pdf);self.assertIsNone(row.docx)

    def test_invalid_duplicate_and_image_only_upload(self):
        path=self.root+'/gestor'
        self.assertEqual(self.client.post(path,data={'report_date':'2026-09-01'},files={'document':('bad.pdf',b'%PDFbroken','application/pdf')}).status_code,400)
        content=docx_bytes('Relatório único')
        first=self.client.post(path,data={'report_date':'2026-09-01'},files={'document':('one.docx',content)},follow_redirects=False)
        self.assertEqual(first.status_code,303)
        self.assertEqual(self.client.post(path,data={'report_date':'2026-09-01'},files={'document':('one.docx',content)}).status_code,409)
        from reportlab.pdfgen import canvas
        out=io.BytesIO();c=canvas.Canvas(out);c.rect(10,10,50,50);c.showPage();c.save()
        result=self.client.post(path,data={'report_date':'2026-09-02'},files={'document':('image.pdf',out.getvalue())},follow_redirects=False)
        self.assertEqual(result.status_code,303)
        page=self.client.get(result.headers['location']);self.assertIn('sem texto extraível',page.text)
        self.assertIn('Consultar original',page.text)

    def test_conflicts_never_double_count_or_invent_zero(self):
        def p(value,kind='structured',ref='entry:1'):return {'date':'2026-09-01','key':'vehicles_total','dimension':'Geral','value':str(value),'kind':kind,'source':ref}
        metrics,conflicts=aggregate_metrics([p(10),p(10,'external','manager:1')])
        self.assertEqual(metrics[0]['value'],'10');self.assertEqual(conflicts,[])
        metrics,conflicts=aggregate_metrics([p(10),p(20,'external','manager:1')])
        self.assertEqual(metrics[0]['value'],'10');self.assertTrue(conflicts)
        metrics,conflicts=aggregate_metrics([p(10),p(20,'structured','entry:2')])
        self.assertEqual(metrics,[]);self.assertTrue(conflicts[0]['excluded'])
        self.assertEqual(aggregate_metrics([]),([],[]))

    def test_cctv_failure_cleaning_checklist_and_historical_availability(self):
        root='/operacoes-internas/cctv';today=date.today()
        created=self.client.post(root,data={'code':'EN6','area':'Entrada','model':'Modelo de teste'},follow_redirects=False)
        self.assertEqual(created.status_code,303);camera_id=int(created.headers['location'].split('/')[-1])
        observed=datetime.now(timezone(timedelta(hours=2))).strftime('%Y-%m-%dT%H:%M')
        result=self.client.post(f'{root}/{camera_id}/estado',data={'status':'Necessita Limpeza','effective_at':observed,'priority':'Crítica','needs_cleaning':'on','notes':'Imagem obstruída.'},follow_redirects=False)
        self.assertEqual(result.status_code,303,result.text)
        self.db.expire_all();stats=cctv_snapshot(self.db,today,today)
        self.assertEqual(stats['failed'],1);self.assertEqual(stats['needs_cleaning'],1);self.assertEqual(stats['availability'],0)
        self.assertIsNotNone(self.db.scalar(select(OperationalPending).where(OperationalPending.camera_id==camera_id)))
        schedule=self.client.post(f'{root}/{camera_id}/programar',data={'starts_on':str(today),'interval_days':7,'owner_id':self.finance_user.id},follow_redirects=False)
        self.assertEqual(schedule.status_code,303)
        self.db.expire_all();plan=self.db.scalar(select(CctvSchedule).where(CctvSchedule.camera_id==camera_id))
        inspection=self.client.post(f'{root}/inspecoes/{plan.id}',data={'scheduled_on':str(today),'result':'Concluído','notes':'Limpeza efetuada.'},follow_redirects=False)
        self.assertEqual(inspection.status_code,303)
        stats=cctv_snapshot(self.db,today,today);self.assertEqual(stats['compliance'],100)
        # A cleaning result does not fabricate a new operational observation.
        self.assertEqual(stats['failed'],1)
        self.assertEqual(self.client.post(f'{root}/inspecoes/{plan.id}',data={'scheduled_on':str(today),'result':'Concluído'}).status_code,409)
        for page in [root,f'{root}/{camera_id}',root+'/inspecoes','/operacoes-internas/pendencias']:
            response=self.client.get(page);self.assertEqual(response.status_code,200,response.text[:100])

    def test_pending_carries_over_and_requires_verified_closure(self):
        today=date.today()
        row=create_pending(self.db,self.finance_user,'unit-test','maintenance','Bomba de incêndio em curto-circuito',opened=today-timedelta(days=10),priority='Crítica')
        self.db.commit()
        snap=build_snapshot(self.db,'maintenance',today,today)
        self.assertEqual(snap['pending'][0]['id'],row.id)
        self.assertEqual(self.client.post(f'/operacoes-internas/pendencias/{row.id}',data={'revision':row.revision,'status':'Closed','notes':'Saltar verificação','owner_id':self.finance_user.id}).status_code,400)
        for state in ['Assigned','In Progress','Executed','Verified','Closed']:
            self.db.expire_all();row=self.db.get(OperationalPending,row.id)
            result=self.client.post(f'/operacoes-internas/pendencias/{row.id}',data={'revision':row.revision,'status':state,'notes':'Ação documentada.','owner_id':self.finance_user.id},follow_redirects=False)
            self.assertEqual(result.status_code,303,result.text)

    def test_permissions_and_drafts_not_visible_to_other_users(self):
        day=date(2026,9,1);self.seed_daily(day);report_id=self.generate('security','weekly',day)
        self.login('blocked')
        self.assertEqual(self.client.get(self.root).status_code,200)
        self.assertEqual(self.client.get(self.root+f'/{report_id}').status_code,403)
        self.assertEqual(self.client.post(self.root+'/gerar',data={'department':'security','period':'weekly','anchor':str(day)}).status_code,403)
        self.assertEqual(self.client.post(self.root+'/gestor',data={'report_date':str(day)}).status_code,403)
        self.assertEqual(self.client.post('/operacoes-internas/cctv',data={'code':'X','area':'Y'}).status_code,403)
        self.assertEqual(self.client.get('/operacoes-internas/cctv').status_code,403)

    def test_structured_entries_create_one_pending_and_official_daily(self):
        base='/operacoes-internas/relatorios-departamentais'
        payload={'department_key':'maintenance','draft_key':str(uuid4()),'report_date':str(date.today()),'activities':'Intervenções do turno.'}
        draft=self.client.post(base+'/rascunho',data=payload,headers=self.headers).json()
        result=self.client.post(self.root+f'/diarios/{draft["id"]}/dados',data={'category':'maintenance','title':'Bomba com avaria','requires_action':'on','occurrence_key':'BOMBA-01','priority':'Alta'},follow_redirects=False)
        self.assertEqual(result.status_code,303,result.text)
        self.assertEqual(self.client.get(self.root+f'/diarios/{draft["id"]}/dados').status_code,200)
        self.db.expire_all();daily=self.db.get(DepartmentDailyReport,draft['id'])
        from app.services.department_drafts import draft_version
        submitted=self.client.post(base,data={**payload,'draft_id':draft['id'],'draft_version':draft_version(daily),'status':'Submitted'},headers=self.headers)
        self.assertEqual(submitted.status_code,200,submitted.text)
        self.db.expire_all();official=self.db.scalar(select(OperationalReport).where(OperationalReport.source_daily_id==draft['id']))
        self.assertIsNotNone(official);self.assertEqual(official.status,'Submitted')
        self.assertIsNotNone(self.db.scalar(select(OperationalPending).where(OperationalPending.source_key=='occurrence:maintenance:BOMBA-01')))
        self.assertEqual(self.client.post(base+f'/{draft["id"]}/validar',data={'status':'Draft'}).status_code,409)
        self.assertEqual(self.client.get(base+f'/{draft["id"]}/texto').status_code,404)

    def test_binary_snapshot_and_additive_migration_idempotence(self):
        from app.services.sync import _json_value,_coerce_value
        from app.maintenance.migrate_operational_reports import migrate
        content=b'\x00\xffPDF test'
        self.assertEqual(_coerce_value(OperationalReport.__table__.c.pdf,_json_value(content)),content)
        migrate(self.engine);migrate(self.engine)
        self.db.expire_all();self.assertIsNotNone(self.db.get(User,self.finance_user.id))

    def test_manager_data_correction_preserves_original_and_old_values(self):
        day=date(2026,9,2);source_id=self.manager(day,[('vehicles_total','Geral',100)])
        original=self.client.get(self.root+f'/gestor/{source_id}/original').content
        response=self.client.post(self.root+f'/gestor/{source_id}/versao',follow_redirects=False)
        self.assertEqual(response.status_code,303)
        next_id=int(response.headers['location'].split('/')[-1]);revision=self.db.get(ManagerReportSource,next_id).revision
        result=self.client.post(self.root+f'/gestor/{next_id}',data={'revision':revision,'action':'review','metric_0_key':'vehicles_total','metric_0_dimension':'Geral','metric_0_value':'120','notes':'Corrigido após conferência do original.'},headers=self.headers)
        self.assertEqual(result.status_code,200,result.text)
        self.db.expire_all()
        self.assertEqual(json.loads(self.db.get(ManagerReportSource,source_id).metrics)[0]['value'],'100')
        self.assertEqual(self.client.get(self.root+f'/gestor/{next_id}/original').content,original)
        snapshot=build_snapshot(self.db,'consolidated',day,day)
        self.assertEqual(snapshot['metrics'][0]['value'],'120');self.assertEqual(snapshot['conflicts'],[])

    def test_overdue_notice_is_grouped_and_not_repeated_after_read(self):
        from app.services.cctv import notify_overdue
        today=date.today()
        row=create_pending(self.db,self.finance_user,'overdue-test','it','Verificar gravação',owner=self.finance_user.id,due=today-timedelta(days=1))
        self.db.commit();notify_overdue(self.db,['it']);notify_overdue(self.db,['it'])
        notices=self.db.scalars(select(Notification).where(Notification.module=='PendenciasOperacionais',Notification.record_id==str(row.id))).all()
        self.assertEqual(len(notices),1)
        notices[0].is_read=True;self.db.commit();notify_overdue(self.db,['it'])
        self.assertEqual(len(self.db.scalars(select(Notification).where(Notification.record_id==str(row.id),Notification.module=='PendenciasOperacionais')).all()),1)

    def test_midnight_maputo_observation_and_configurable_week(self):
        day=date(2026,9,10)
        camera=CctvCamera(code='MIDNIGHT',area='Entrada',registered_on=day)
        self.db.add(camera);self.db.flush()
        self.db.add(CctvStatusLog(camera_id=camera.id,effective_at=datetime(2026,9,9,22,30,tzinfo=timezone.utc),status='Operacional',operational=True,full_recording=True,created_by_id=self.finance_user.id));self.db.commit()
        self.assertEqual(cctv_snapshot(self.db,day,day)['operational'],1)
        self.assertEqual(cctv_snapshot(self.db,day-timedelta(days=1),day-timedelta(days=1))['total'],0)
        from app.services.reporting_common import period_window
        self.assertEqual(period_window('weekly','2026-09-10',6),(date(2026,9,6),date(2026,9,12)))
        self.assertEqual(period_window('monthly','2028-02-14'),(date(2028,2,1),date(2028,2,29)))

    def test_recurring_reference_is_one_case_with_multiple_sources(self):
        for day in [date(2026,9,1),date(2026,9,2)]:
            report=self.seed_daily(day,'maintenance')
            self.db.add(DailyReportEntry(report_id=report.id,category='maintenance',title='Bomba continua indisponível',occurrence_key='BOMBA-01',priority='Crítica' if day.day==2 else 'Normal'))
        self.db.commit()
        snapshot=build_snapshot(self.db,'maintenance',date(2026,9,1),date(2026,9,2))
        self.assertEqual(len(snapshot['events']),1)
        self.assertEqual(len(snapshot['events'][0]['references']),2)
        self.assertEqual(snapshot['events'][0]['priority'],'Crítica')
        self.assertEqual(sum(s['kind']=='entry' for s in snapshot['sources']),2)

    def test_empty_period_and_invalid_numeric_values_are_rejected(self):
        self.assertEqual(self.client.post(self.root+'/gerar',data={'department':'security','period':'monthly','anchor':'2026-09-01'}).status_code,400)
        from app.services.reporting_common import metric_value
        from fastapi import HTTPException
        for key,value in [('vehicles_in','2.5'),('diesel_level','101'),('revenue','1.001'),('fuel_litres','-1')]:
            with self.subTest(key=key),self.assertRaises(HTTPException):metric_value(key,value)
