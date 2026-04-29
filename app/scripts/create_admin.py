import argparse
import asyncio

from app.core.database import close_db, init_db
from app.modules.users.models import UserRole
from app.modules.users.schemas import UserRegister
from app.modules.users.service import create_user, get_user_by_email, get_user_by_username, update_user_role


async def create_or_promote_admin(email: str, username: str, password: str, full_name: str | None) -> None:
    await init_db()
    try:
        existing_user = await get_user_by_email(email)
        if existing_user:
            await update_user_role(existing_user, UserRole.admin)
            existing_user.is_active = True
            await existing_user.save()
            print(f"Пользователь {email} назначен администратором.")
            return

        username_owner = await get_user_by_username(username)
        if username_owner:
            await update_user_role(username_owner, UserRole.admin)
            username_owner.is_active = True
            await username_owner.save()
            print(f"Пользователь {username} назначен администратором.")
            return

        payload = UserRegister(email=email, username=username, password=password, full_name=full_name)
        user = await create_user(payload, role=UserRole.admin)
        print(f"Администратор создан: {user.email}")
    finally:
        await close_db()


def main() -> None:
    parser = argparse.ArgumentParser(description="Создать первого администратора или повысить существующего пользователя")
    parser.add_argument("--email", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--full-name", default=None)
    args = parser.parse_args()

    asyncio.run(
        create_or_promote_admin(
            email=args.email,
            username=args.username,
            password=args.password,
            full_name=args.full_name,
        )
    )


if __name__ == "__main__":
    main()
