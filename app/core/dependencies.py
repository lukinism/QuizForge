from collections.abc import Callable
from typing import Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import get_settings
from app.core.security import decode_token
from app.modules.users.models import User, UserRole


bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user_optional(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> User | None:
    settings = get_settings()
    token = request.cookies.get(settings.access_cookie_name)

    if not token and credentials is not None:
        token = credentials.credentials

    if not token:
        return None

    payload = decode_token(token, expected_type="access")
    if not payload:
        return None

    user_id = payload.get("sub")
    if not user_id:
        return None

    user = await User.get(user_id)
    return user


async def get_current_user(
    current_user: User | None = Depends(get_current_user_optional),
) -> User:
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Нужно войти в систему, чтобы продолжить.",
        )
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Ваш аккаунт заблокирован.",
        )
    return current_user


async def get_refresh_user(request: Request) -> User:
    settings = get_settings()
    token = request.cookies.get(settings.refresh_cookie_name)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Сессия истекла. Войдите в систему снова.",
        )

    payload = decode_token(token, expected_type="refresh")
    if not payload or "sub" not in payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Сессия истекла. Войдите в систему снова.",
        )

    user = await User.get(payload["sub"])
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Аккаунт заблокирован или больше недоступен.",
        )
    return user


def require_roles(*roles: UserRole) -> Callable[..., Any]:
    async def dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="У вас нет прав для доступа к этому разделу.",
            )
        return current_user

    return dependency
