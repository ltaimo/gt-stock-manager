from fastapi import APIRouter, Depends, Request

from app.models.core import User
from app.routers.common import templates
from app.security import current_user

router = APIRouter()


@router.get("/sobre")
def about(request: Request, user: User = Depends(current_user)):
    return templates.TemplateResponse(request, "about.html", {"request": request, "user": user})
