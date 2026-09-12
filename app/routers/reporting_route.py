from fastapi import HTTPException
from fastapi.routing import APIRoute
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

class ReportingRoute(APIRoute):
    """Translate concurrent flush/commit conflicts without leaking database detail."""
    def get_route_handler(self):
        original=super().get_route_handler()
        async def handler(request):
            try:return await original(request)
            except (IntegrityError,StaleDataError) as exc:
                raise HTTPException(409,'O registo já existe ou foi atualizado noutra sessão. Atualize a página para continuar.') from exc
        return handler
