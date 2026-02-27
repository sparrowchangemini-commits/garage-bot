from aiogram import types


def main_menu_keyboard() -> types.ReplyKeyboardMarkup:
    keyboard = [
        [
            types.KeyboardButton(text="🔍 Найти вещь"),
        ],
        [
            types.KeyboardButton(text="📦 Мои бронирования"),
            types.KeyboardButton(text="📚 Мои вещи"),
        ],
    ]
    return types.ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        one_time_keyboard=False,
    )


def back_to_main_keyboard() -> types.ReplyKeyboardMarkup:
    return types.ReplyKeyboardMarkup(
        keyboard=[[types.KeyboardButton(text="⬅️ На главную")]],
        resize_keyboard=True,
    )


def items_list_keyboard(items: list[tuple[int, str]]) -> types.InlineKeyboardMarkup:
    """Список вещей: (item_id, label). Каждая вещь — отдельная кнопка."""
    kb = types.InlineKeyboardMarkup(row_width=1)
    for item_id, label in items:
        kb.add(
            types.InlineKeyboardButton(
                text=label,
                callback_data=f"item:{item_id}",
            )
        )
    return kb


def item_actions_keyboard(
    item_id: int, is_owner: bool = False, owner_handle: str | None = None
) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup()
    if is_owner:
        kb.add(
            types.InlineKeyboardButton(
                text="📅 Заблокировать даты как владелец",
                callback_data=f"selfbook:{item_id}",
            )
        )
        kb.add(
            types.InlineKeyboardButton(
                text="📋 Все бронирования",
                callback_data=f"item_bookings:{item_id}",
            )
        )
    else:
        kb.add(
            types.InlineKeyboardButton(
                text="🤝 Забронировать",
                callback_data=f"book:{item_id}",
            )
        )
        if owner_handle and owner_handle.strip():
            username = owner_handle.strip().lstrip("@")
            if username:
                kb.add(
                    types.InlineKeyboardButton(
                        text="💬 Написать владельцу",
                        url=f"https://t.me/{username}",
                    )
                )
    return kb

