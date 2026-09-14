import io
import unittest
from datetime import date
from types import SimpleNamespace
from PIL import Image
from app.services.report_dashboard import dashboard_data,dashboard_images

class ReportDashboardTests(unittest.TestCase):
    def test_metrics_keep_dimensions_and_modes_and_visible_unknowns(self):
        report=SimpleNamespace(date_from=date(2026,9,1),date_to=date(2026,9,7),department_key='security')
        def metric(dimension,value,mode='last'):
            return {'key':'vehicles_parked','dimension':dimension,'label':'Viaturas em parque','unit':'viaturas','mode':mode,'value':str(value),'days':1,'trend':[{'date':'2026-09-01','value':str(value)}]}
        snapshot={'sources':[],'events':[],'pending':[],'missing':[{'date':'2026-09-02'}], 'metrics':[metric('Geral',30),metric('Importações',20),metric('Saldo observado',-5)],'conflicts':[]}
        data=dashboard_data(report,snapshot)
        self.assertEqual(data['cards'][1][1],'6/7')
        self.assertEqual([r['values'] for r in data['charts'][0]['rows']],[[30.0],[20.0],[-5.0]])
        self.assertIn('Último saldo',data['charts'][0]['note'])
        import base64
        for visual in dashboard_images(data):
            image=Image.open(io.BytesIO(base64.b64decode(visual['data'])))
            self.assertEqual(image.width,1200)

    def test_empty_dashboard_never_invents_numeric_observations(self):
        report=SimpleNamespace(date_from=date(2026,9,1),date_to=date(2026,9,7),department_key='it')
        data=dashboard_data(report,{'missing':[{}]*7})
        self.assertFalse(data['has_metrics']);self.assertEqual(data['charts'],[])
        self.assertEqual(data['cards'][1][1],'0/7')
        self.assertEqual(len(dashboard_images(data)),1)

    def test_all_dimensions_are_rendered_beyond_old_six_chart_limit(self):
        report=SimpleNamespace(date_from=date(2026,9,1),date_to=date(2026,9,7),department_key='it')
        metrics=[{'key':'tickets_resolved','dimension':f'Sistema {i}','label':'Tickets resolvidos','unit':'tickets','mode':'sum','value':'3','days':2,'trend':[{'date':'2026-09-01','value':'1'},{'date':'2026-09-03','value':'2'}]} for i in range(9)]
        data=dashboard_data(report,{'metrics':metrics})
        self.assertEqual(len([c for c in data['charts'] if c['kind']=='trend']),9)
        self.assertEqual(sum(len(c['rows']) for c in data['charts'] if c['kind']=='bars'),9)
