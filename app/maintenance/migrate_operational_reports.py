"""Explicit, additive migration; never executed inside an HTTP request."""
import json
from sqlalchemy import inspect, text
from app.database import Base, engine
from app.models import reporting

TABLES = [value.__table__ for value in vars(reporting).values() if isinstance(value, type) and hasattr(value,'__table__')]

def migrate(bind=engine):
    existing=set(inspect(bind).get_table_names())
    if not {'users','department_daily_reports','financial_daily_imports','products'} <= existing:
        raise RuntimeError('Prepare primeiro o schema existente antes da migração de relatórios operacionais.')
    Base.metadata.create_all(bind, tables=TABLES, checkfirst=True)
    grants={
        'Gestor Operacional':{'operational_reports_manage','operational_pending_manage'},
        'Operações':{'operational_reports_manage','operational_pending_manage'},
        'Director de Informatica':{'cctv_manage'},'IT Supervisor':{'cctv_manage'},
        'Admin':{'operational_reports_manage','operational_reports_receive','operational_reports_settings','cctv_manage','operational_pending_manage'},
    }
    for role in ['Chefe do Terminal','Director do Terminal','Director Financeiro','Administrador Delegado','PCA']:
        grants[role]={'operational_reports_receive'}
    with bind.begin() as connection:
        if bind.dialect.name == 'postgresql':
            for table in TABLES:
                connection.execute(text(f'ALTER TABLE "{table.name}" ENABLE ROW LEVEL SECURITY'))
        for role in connection.execute(text('SELECT id, name, permissions FROM roles')).mappings():
            from app.security import DEFAULT_ROLE_PERMISSIONS
            try:permissions=set(json.loads(role['permissions'] or '[]'))
            except (ValueError,TypeError):permissions=set()
            if not permissions:permissions=set(DEFAULT_ROLE_PERMISSIONS.get(role['name'],set()))
            permissions.discard('internal_ops_reports_copy')
            permissions.update(grants.get(role['name'],set()))
            connection.execute(text('UPDATE roles SET permissions=:permissions WHERE id=:id'),{'id':role['id'],'permissions':json.dumps(sorted(permissions))})

if __name__=='__main__':
    migrate()
    print('Schema de relatórios operacionais preparado; dados existentes preservados.')
