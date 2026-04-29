from app.core.audit import log_action
from app.core.security import create_access_token, create_refresh_token
from app.modules.auth.schemas import TokenPair
from app.modules.users.models import User, UserRole
from app.modules.users.schemas import UserRegister
from app.modules.users.service import authenticate_user, create_user


async def register_student(payload: UserRegister) -> User:
    user = await create_user(payload, role=UserRole.student)
    await log_action(str(user.id), "register", "user", str(user.id), {"role": user.role.value})
    return user


async def login_user(email: str, password: str) -> User:
    user = await authenticate_user(email=email, password=password)
    await log_action(str(user.id), "login", "user", str(user.id))
    return user


def build_token_pair(user: User) -> TokenPair:
    return TokenPair(
        access_token=create_access_token(subject=str(user.id), role=user.role.value),
        refresh_token=create_refresh_token(subject=str(user.id), role=user.role.value),
    )
