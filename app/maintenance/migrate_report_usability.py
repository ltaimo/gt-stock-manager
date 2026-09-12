"""Add report configuration and recoverable deletion storage; no role changes."""
from sqlalchemy import inspect
from app.models.reporting import ReportFormSchema, ReportDeletion

TABLES=(ReportFormSchema.__table__,ReportDeletion.__table__)


def migrate(engine):
    with engine.begin() as connection:
        for table in TABLES:
            table.create(connection,checkfirst=True)
            if engine.dialect.name=='postgresql':
                connection.exec_driver_sql(f'ALTER TABLE "{table.name}" ENABLE ROW LEVEL SECURITY')
    return all(inspect(engine).has_table(table.name) for table in TABLES)
