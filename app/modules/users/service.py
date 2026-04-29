from fastapi import HTTPException, status

from app.core.security import hash_password, verify_password
from app.core.utils import parse_object_id, utcnow
from app.modules.users.models import User, UserRole
from app.modules.users.schemas import UserRegister


async def list_users() -> list[User]:
    return await User.find_all().sort("-created_at").to_list()


async def get_user_by_email(email: str) -> User | None:
    return await User.find_one(User.email == email)


async def get_user_by_username(username: str) -> User | None:
    return await User.find_one(User.username == username)


async def get_user_by_id(user_id: str) -> User | None:
    return await User.get(parse_object_id(user_id))


async def create_user(payload: UserRegister, role: UserRole = UserRole.student) -> User:
    if await get_user_by_email(payload.email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Пользователь с таким адресом электронной почты уже зарегистрирован.",
        )
    if await get_user_by_username(payload.username):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Это имя пользователя уже занято.",
        )

    user = User(
        email=payload.email,
        username=payload.username,
        full_name=payload.full_name,
        password_hash=hash_password(payload.password),
        role=role,
    )
    await user.insert()
    return user


async def authenticate_user(email: str, password: str) -> User:
    user = await get_user_by_email(email)
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный адрес электронной почты или пароль.",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Ваш аккаунт заблокирован.",
        )
    return user


async def update_user_role(user: User, role: UserRole) -> User:
    user.role = role
    user.updated_at = utcnow()
    await user.save()
    return user


async def set_user_active_state(user: User, is_active: bool) -> User:
    user.is_active = is_active
    user.updated_at = utcnow()
    await user.save()
    return user
