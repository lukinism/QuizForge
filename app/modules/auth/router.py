from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from app.core.dependencies import get_current_user_optional, get_refresh_user
from app.core.security import clear_auth_cookies, set_auth_cookies
from app.core.templates import templates
from app.modules.auth.service import build_token_pair, login_user, register_student
from app.modules.users.models import User
from app.modules.users.schemas import UserRegister


router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/login")
async def login_page(
    request: Request,
    current_user: User | None = Depends(get_current_user_optional),
):
    if current_user:
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="auth/login.html",
        context={"current_user": None},
    )


@router.post("/login")
async def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next: str = Form(""),
):
    try:
        user = await login_user(email=email, password=password)
    except Exception as exc:  # noqa: BLE001
        return templates.TemplateResponse(
            request=request,
            name="auth/login.html",
            context={"current_user": None, "error": getattr(exc, "detail", str(exc)), "email": email},
            status_code=getattr(exc, "status_code", 400),
        )

    token_pair = build_token_pair(user)
    redirect_target = next if next.startswith("/") else "/"
    response = RedirectResponse(url=redirect_target, status_code=303)
    set_auth_cookies(response, token_pair.access_token, token_pair.refresh_token)
    return response


@router.get("/register")
async def register_page(
    request: Request,
    current_user: User | None = Depends(get_current_user_optional),
):
    if current_user:
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="auth/register.html",
        context={"current_user": None},
    )


@router.post("/register")
async def register_submit(
    request: Request,
    email: str = Form(...),
    username: str = Form(...),
    full_name: str = Form(""),
    password: str = Form(...),
):
    try:
        payload = UserRegister(
            email=email,
            username=username,
            full_name=full_name or None,
            password=password,
        )
        user = await register_student(payload)
    except Exception as exc:  # noqa: BLE001
        return templates.TemplateResponse(
            request=request,
            name="auth/register.html",
            context={
                "current_user": None,
                "error": getattr(exc, "detail", str(exc)),
                "email": email,
                "username": username,
                "full_name": full_name,
            },
            status_code=getattr(exc, "status_code", 400),
        )

    token_pair = build_token_pair(user)
    response = RedirectResponse(url="/student", status_code=303)
    set_auth_cookies(response, token_pair.access_token, token_pair.refresh_token)
    return response


@router.post("/logout")
async def logout_submit():
    response = RedirectResponse(url="/auth/login", status_code=303)
    clear_auth_cookies(response)
    return response


@router.post("/refresh")
async def refresh_access_token(user: User = Depends(get_refresh_user)):
    token_pair = build_token_pair(user)
    response = RedirectResponse(url="/", status_code=303)
    set_auth_cookies(response, token_pair.access_token, token_pair.refresh_token)
    return response
