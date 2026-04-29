from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import HTTPException as FastAPIHTTPException
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings
from app.core.database import close_db, init_db
from app.core.templates import templates
from app.core.web import (
    build_login_redirect_url,
    build_redirect_back_url,
    humanize_error,
    request_prefers_html,
    resolve_current_user_from_request,
    toast_level_for_status,
)
from app.modules.attempts.router import router as attempts_router
from app.modules.auth.router import router as auth_router
from app.modules.dashboard.router import router as dashboard_router
from app.modules.groups.router import router as groups_router
from app.modules.reports.router import router as reports_router
from app.modules.tests.router import router as tests_router
from app.modules.users.router import router as users_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    yield
    await close_db()


settings = get_settings()
app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")

ALLOWED_UPLOAD_EXTENSIONS = {
    ".apng",
    ".avi",
    ".bmp",
    ".csv",
    ".docx",
    ".gif",
    ".jpeg",
    ".jpg",
    ".m4a",
    ".mkv",
    ".mov",
    ".mp3",
    ".mp4",
    ".ogg",
    ".pdf",
    ".png",
    ".pptx",
    ".txt",
    ".wav",
    ".webm",
    ".webp",
    ".xlsx",
}
DOWNLOAD_UPLOAD_EXTENSIONS = {".csv", ".docx", ".pdf", ".pptx", ".txt", ".xlsx"}


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
    return response


@app.get("/uploads/{filename}")
async def uploaded_file(filename: str, request: Request):
    current_user = await resolve_current_user_from_request(request)
    if current_user is None:
        raise HTTPException(status_code=401, detail="Войдите в систему.")

    path = settings.upload_storage_dir / filename
    if (
        Path(filename).name != filename
        or filename.startswith(".")
        or path.suffix.lower() not in ALLOWED_UPLOAD_EXTENSIONS
        or not path.is_file()
    ):
        raise HTTPException(status_code=404, detail="Файл не найден.")

    if path.suffix.lower() in DOWNLOAD_UPLOAD_EXTENSIONS:
        return FileResponse(path, filename=filename, content_disposition_type="attachment")
    return FileResponse(path)

app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(users_router)
app.include_router(groups_router)
app.include_router(tests_router)
app.include_router(attempts_router)
app.include_router(reports_router)


@app.exception_handler(FastAPIHTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    detail = humanize_error(exc.detail)
    level = toast_level_for_status(exc.status_code)

    if not request_prefers_html(request):
        return JSONResponse(status_code=exc.status_code, content={"detail": detail})

    current_user = await resolve_current_user_from_request(request)

    if exc.status_code == 401:
        return RedirectResponse(
            url=build_login_redirect_url(request, detail, level),
            status_code=303,
        )

    if request.method != "GET":
        return RedirectResponse(
            url=build_redirect_back_url(request, detail, level),
            status_code=303,
        )

    if exc.status_code == 403:
        return templates.TemplateResponse(
            request=request,
            name="403.html",
            context={"current_user": current_user, "detail": detail},
            status_code=403,
        )
    if exc.status_code == 404:
        return templates.TemplateResponse(
            request=request,
            name="404.html",
            context={"current_user": current_user, "detail": detail},
            status_code=404,
        )
    return templates.TemplateResponse(
        request=request,
        name="error.html",
        context={"current_user": current_user, "detail": detail, "status_code": exc.status_code},
        status_code=exc.status_code,
    )
