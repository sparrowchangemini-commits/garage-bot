from aiogram.types import User as TgUser

from .db import db_session
from .models import User


def get_or_create_user(tg: TgUser) -> User:
    with db_session() as session:
        user = session.query(User).get(tg.id)
        if user is None:
            user = User(tg_id=tg.id)
            session.add(user)

        user.username = tg.username
        user.first_name = tg.first_name
        user.last_name = tg.last_name

        if tg.username:
            handle = f"@{tg.username.lower()}"
            # если в таблице владелец использует такой же ник, привязываем
            user.owner_handle = handle

        return user

