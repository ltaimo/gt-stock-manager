import base64
import json
import time
import unittest
from uuid import uuid4

from itsdangerous import TimestampSigner
from sqlalchemy import select, func

from tests import test_finance as fixture
from app.config import get_settings
from app.models.core import DepartmentDailyReport


class DepartmentDraftTests(unittest.TestCase):
    tearDown = fixture.FinanceModuleTests.tearDown
    override_db = fixture.FinanceModuleTests.override_db
    login = fixture.FinanceModuleTests.login

    def setUp(self):
        fixture.FinanceModuleTests.setUp(self)
        self.finance_role.name = 'SuperAdmin'
        self.user_role.name = 'Admin'
        self.db.commit()
        self.login()
        self.url = '/operacoes-internas/relatorios-departamentais'
        self.data = {'department_key': 'security', 'draft_key': str(uuid4()), 'draft_id': '', 'team__0': 'Nome a confirmar'}
        self.headers = {'Accept': 'application/json'}

    def save(self):
        return self.client.post(self.url + '/rascunho', data=self.data, headers=self.headers)

    def test_partial_save_resume_and_submit_same_record(self):
        first = self.save()
        self.assertEqual(first.status_code, 200)
        saved_id = first.json()['id']
        self.assertEqual(first.json()['status'], 'Draft')
        second = self.save()
        self.assertEqual(second.json()['id'], saved_id)
        self.assertEqual(self.db.scalar(select(func.count(DepartmentDailyReport.id))), 1)
        page = self.client.get(self.url + f'?department=security&draft_id={saved_id}')
        self.assertIn('Nome a confirmar', page.text)
        self.assertIn('Continuar rascunho', page.text)
        bundle = self.client.get('/relatorios/operacoes-internas/departamentos')
        self.assertNotIn('Nome a confirmar', bundle.text)
        self.data.update(draft_id=saved_id, report_date='2026-09-08', incidents='Sem incidentes', status='Submitted')
        final = self.client.post(self.url, data=self.data, headers=self.headers)
        self.assertEqual(final.json()['id'], saved_id)
        self.assertEqual(final.json()['status'], 'Submitted')
        self.assertEqual(self.save().status_code, 409)
        self.assertEqual(self.db.scalar(select(func.count(DepartmentDailyReport.id))), 1)

    def test_draft_cannot_be_edited_by_another_user_or_department(self):
        saved_id = self.save().json()['id']
        self.login('blocked')  # Admin still cannot overwrite another author's draft.
        self.data['draft_id'] = saved_id
        self.assertEqual(self.save().status_code, 403)
        self.assertEqual(self.client.get(self.url + f'?department=security&draft_id={saved_id}').status_code, 403)
        self.login()
        self.data['department_key'] = 'maintenance'
        self.assertEqual(self.save().status_code, 403)

    def test_session_expires_and_draft_survives_login(self):
        saved_id = self.save().json()['id']
        signer = TimestampSigner(str(get_settings().secret_key))
        cookie = self.client.cookies.get('session')
        payload = json.loads(base64.b64decode(signer.unsign(cookie)))
        payload['last_activity_at'] = time.time() - 1900
        expired = signer.sign(base64.b64encode(json.dumps(payload).encode())).decode()
        self.client.cookies.clear()
        self.client.cookies.set('session', expired)
        self.assertEqual(self.client.post('/session/activity', headers=self.headers).status_code, 401)
        self.assertEqual(self.client.get(self.url, follow_redirects=False).status_code, 303)
        self.login()
        self.assertEqual(self.client.post('/session/activity', headers=self.headers).status_code, 200)
        resumed = self.client.get(self.url + f'?department=security&draft_id={saved_id}')
        self.assertEqual(resumed.status_code, 200)
        self.assertIn('Nome a confirmar', resumed.text)

    def test_empty_submission_rejected_without_destroying_draft(self):
        saved_id = self.save().json()['id']
        self.data.update(draft_id=saved_id, status='Submitted')
        self.assertEqual(self.client.post(self.url, data=self.data, headers=self.headers).status_code, 400)
        self.db.expire_all()
        self.assertEqual(self.db.get(DepartmentDailyReport, saved_id).status, 'Draft')

    def test_old_version_cannot_overwrite_newer_draft(self):
        first = self.save().json()
        self.data.update(draft_id=first['id'], draft_version=first['version'], team__0='Atualizado')
        second = self.save()
        self.assertEqual(second.status_code, 200)
        self.data['team__0'] = 'Cópia antiga'
        self.assertEqual(self.save().status_code, 409)
        self.db.expire_all()
        self.assertIn('Atualizado', self.db.get(DepartmentDailyReport, first['id']).team)
