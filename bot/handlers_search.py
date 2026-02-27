from aiogram import Bot, Dispatcher, types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from sqlalchemy import func

from .config import load_settings
from .db import db_session
from .keyboards import items_list_keyboard, item_actions_keyboard, main_menu_keyboard
from .models import Item
from .users import get_or_create_user
from .utils import _e, format_price


class SearchStates(StatesGroup):
    active = State()


async def _run_search(
    chat_id: int,
    bot: Bot,
    query: str,
    area: str | None,
    type_filter: str | None,
    owner_filter: str | None,
    extra_markup: types.InlineKeyboardMarkup | None = None,
) -> bool:
    """Выполняет поиск и отправляет результат. Возвращает True если есть результаты."""
    with db_session() as session:
        q = session.query(Item)
        if query and query.strip() and query.strip() != "*":
            like = f"%{query.strip().lower()}%"
            q = q.filter(func.lower(Item.name).like(like))
        if area:
            q = q.filter(Item.area.isnot(None), Item.area == area)
        if type_filter:
            q = q.filter(Item.type.isnot(None), Item.type == type_filter)
        if owner_filter:
            q = q.filter(Item.owner_handle == owner_filter)
        items = q.order_by(Item.name).limit(30).all()

    if not items:
        return False

    kb_items = [
        (it.id, f"{it.name} · {format_price(it.price_raw)} · {it.area or '—'}")
        for it in items
    ]
    kb = items_list_keyboard(kb_items)
    if extra_markup and extra_markup.inline_keyboard:
        for row in extra_markup.inline_keyboard:
            kb.inline_keyboard.append(row)
    filters_info = []
    if area:
        filters_info.append(f"район: {area}")
    if type_filter:
        filters_info.append(f"тип: {type_filter}")
    if owner_filter:
        filters_info.append(f"владелец: {owner_filter}")
    header = "Вот что удалось найти"
    if filters_info:
        header += f" (фильтры: {', '.join(filters_info)})"
    body = header
    await bot.send_message(chat_id, body, reply_markup=kb, parse_mode="HTML")
    return True


def _filters_keyboard(
    area: str | None, type_filter: str | None, owner_filter: str | None = None
) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup()
    area_label = f"✓ Район: {area}" if area else "Район"
    type_label = f"✓ Тип: {type_filter}" if type_filter else "Тип"
    owner_label = f"✓ Владелец: {owner_filter}" if owner_filter else "Владелец"
    kb.row(
        types.InlineKeyboardButton(text=area_label, callback_data="sf:area"),
        types.InlineKeyboardButton(text=type_label, callback_data="sf:type"),
    )
    kb.row(types.InlineKeyboardButton(text=owner_label, callback_data="sf:owner"))
    if area or type_filter or owner_filter:
        kb.add(types.InlineKeyboardButton(text="Сбросить фильтры", callback_data="sf:clear"))
    return kb


async def show_main_menu(message: types.Message) -> None:
    text = (
        "Привет! Это бот гаражки аренды вещей.\n\n"
        "👉 Здесь можно:\n"
        "• найти вещь по названию;\n"
        "• посмотреть свои бронирования;\n"
        "• как владелец — увидеть свои вещи и брони.\n\n"
        "Выберите действие на клавиатуре ниже."
    )
    await message.answer(text, reply_markup=main_menu_keyboard())


def register_search_handlers(dp: Dispatcher) -> None:
    @dp.message_handler(commands=["start"])
    async def cmd_start(message: types.Message, state: FSMContext) -> None:
        get_or_create_user(message.from_user)
        await state.finish()
        await show_main_menu(message)

    @dp.message_handler(lambda m: m.text and "На главную" in m.text, state="*")
    async def back_to_main(message: types.Message, state: FSMContext) -> None:
        get_or_create_user(message.from_user)
        await state.finish()
        await show_main_menu(message)

    @dp.message_handler(lambda m: m.text and "Найти вещь" in m.text, state="*")
    async def ask_search_query(message: types.Message, state: FSMContext) -> None:
        get_or_create_user(message.from_user)
        await state.set_state(SearchStates.active.state)
        await state.update_data(query="", area=None, type_filter=None, owner_filter=None)
        kb = _filters_keyboard(None, None, None)
        await message.answer(
            "Введите часть названия вещи (или * для всех):\n"
            "Можно также выбрать фильтры по району, типу и владельцу.",
            reply_markup=kb,
        )

    @dp.message_handler(lambda m: m.text and "Добавить свои вещи" in m.text, state="*")
    async def add_own_items(message: types.Message, state: FSMContext) -> None:
        get_or_create_user(message.from_user)
        await state.finish()
        settings = load_settings()
        url = f"https://docs.google.com/spreadsheets/d/{settings.sheets.spreadsheet_id}/edit"
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton(text="📊 Открыть таблицу в браузере", url=url))
        await message.answer(
            "Нажмите кнопку ниже, чтобы открыть таблицу и добавить свои вещи:",
            reply_markup=kb,
        )

    @dp.message_handler(
        lambda m: m.text
        and not m.text.startswith("/")
        and not any(
            key in m.text
            for key in [
                "Найти вещь",
                "Мои бронирования",
                "Мои вещи",
                "На главную",
                "Добавить свои вещи",
            ]
        ),
        state=SearchStates.active,
    )
    async def handle_search_query(message: types.Message, state: FSMContext) -> None:
        get_or_create_user(message.from_user)
        query = (message.text or "").strip()
        if not query:
            return
        if len(query) < 2 and query != "*":
            await message.answer("Введите минимум 2 символа для поиска или * для просмотра всех.")
            return

        data = await state.get_data()
        area = data.get("area")
        type_filter = data.get("type_filter")
        owner_filter = data.get("owner_filter")
        await state.update_data(query=query)

        found = await _run_search(
            message.chat.id,
            message.bot,
            query,
            area,
            type_filter,
            owner_filter,
            extra_markup=_filters_keyboard(area, type_filter, owner_filter),
        )
        if not found:
            await message.answer(
                "Ничего не нашлось. Попробуйте изменить запрос или фильтры.",
                reply_markup=_filters_keyboard(area, type_filter, owner_filter),
            )

    @dp.callback_query_handler(lambda c: c.data and c.data.startswith("sf:"), state=SearchStates.active)
    async def search_filter_callback(callback: types.CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        _, action = callback.data.split(":", 1)
        data = await state.get_data()
        query = data.get("query") or "*"
        area = data.get("area")
        type_filter = data.get("type_filter")
        owner_filter = data.get("owner_filter")

        if action == "clear":
            await state.update_data(area=None, type_filter=None, owner_filter=None)
            await callback.message.edit_text("Фильтры сброшены. Введите запрос или * для всех.")
            return

        if action == "area":
            with db_session() as session:
                rows = session.query(Item.area).filter(Item.area.isnot(None), Item.area != "").distinct().all()
                areas = sorted({r[0].strip() for r in rows if r[0] and r[0].strip()})
            if not areas:
                await callback.answer("Нет данных по районам.", show_alert=True)
                return
            await state.update_data(_areas_picker=areas)
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton(text="Любой район", callback_data="sf:area:_none"))
            for i, a in enumerate(areas):
                kb.add(types.InlineKeyboardButton(text=a, callback_data=f"sf:area:{i}"))
            await callback.message.edit_text("Выберите район:", reply_markup=kb)
            return

        if action == "type":
            with db_session() as session:
                rows = session.query(Item.type).filter(Item.type.isnot(None), Item.type != "").distinct().all()
                types_list = sorted({r[0].strip() for r in rows if r[0] and r[0].strip()})
            if not types_list:
                await callback.answer("Нет данных по типам.", show_alert=True)
                return
            await state.update_data(_types_picker=types_list)
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton(text="Любой тип", callback_data="sf:type:_none"))
            for i, t in enumerate(types_list):
                kb.add(types.InlineKeyboardButton(text=t, callback_data=f"sf:type:{i}"))
            await callback.message.edit_text("Выберите тип вещи:", reply_markup=kb)
            return

        if action == "owner":
            with db_session() as session:
                rows = (
                    session.query(Item.owner_handle)
                    .filter(Item.owner_handle.isnot(None), Item.owner_handle != "")
                    .distinct()
                    .all()
                )
                owners = sorted({r[0].strip() for r in rows if r[0] and r[0].strip()})
            if not owners:
                await callback.answer("Нет данных по владельцам.", show_alert=True)
                return
            await state.update_data(_owners_picker=owners)
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton(text="Любой владелец", callback_data="sf:owner:_none"))
            for i, o in enumerate(owners):
                kb.add(types.InlineKeyboardButton(text=o, callback_data=f"sf:owner:{i}"))
            await callback.message.edit_text("Выберите владельца:", reply_markup=kb)
            return

        if action.startswith("area:"):
            val = action[5:]
            picker = (await state.get_data()).get("_areas_picker") or []
            area = None if val == "_none" else (picker[int(val)] if val.isdigit() and 0 <= int(val) < len(picker) else None)
            await state.update_data(area=area)
            found = await _run_search(
                callback.message.chat.id,
                callback.message.bot,
                query,
                area,
                type_filter,
                owner_filter,
                extra_markup=_filters_keyboard(area, type_filter, owner_filter),
            )
            if not found:
                await callback.message.edit_text(
                    "Ничего не нашлось с такими фильтрами.",
                    reply_markup=_filters_keyboard(area, type_filter, owner_filter),
                )

        elif action.startswith("type:"):
            val = action[5:]
            picker = (await state.get_data()).get("_types_picker") or []
            type_filter = None if val == "_none" else (picker[int(val)] if val.isdigit() and 0 <= int(val) < len(picker) else None)
            await state.update_data(type_filter=type_filter)
            found = await _run_search(
                callback.message.chat.id,
                callback.message.bot,
                query,
                area,
                type_filter,
                owner_filter,
                extra_markup=_filters_keyboard(area, type_filter, owner_filter),
            )
            if not found:
                await callback.message.edit_text(
                    "Ничего не нашлось с такими фильтрами.",
                    reply_markup=_filters_keyboard(area, type_filter, owner_filter),
                )

        elif action.startswith("owner:"):
            val = action[6:]
            picker = (await state.get_data()).get("_owners_picker") or []
            owner_filter = (
                None
                if val == "_none"
                else (picker[int(val)] if val.isdigit() and 0 <= int(val) < len(picker) else None)
            )
            await state.update_data(owner_filter=owner_filter)
            found = await _run_search(
                callback.message.chat.id,
                callback.message.bot,
                query,
                area,
                type_filter,
                owner_filter,
                extra_markup=_filters_keyboard(area, type_filter, owner_filter),
            )
            if not found:
                await callback.message.edit_text(
                    "Ничего не нашлось с такими фильтрами.",
                    reply_markup=_filters_keyboard(area, type_filter, owner_filter),
                )

    @dp.message_handler(
        lambda m: m.text
        and not m.text.startswith("/")
        and not any(k in m.text for k in ["Найти вещь", "Мои бронирования", "Мои вещи", "На главную"]),
        state=None,
    )
    async def handle_search_query_no_state(message: types.Message, state: FSMContext) -> None:
        """Текст вне режима поиска — включаем поиск и обрабатываем."""
        get_or_create_user(message.from_user)
        await state.set_state(SearchStates.active.state)
        await state.update_data(query="", area=None, type_filter=None, owner_filter=None)
        await handle_search_query(message, state)

    @dp.callback_query_handler(lambda c: c.data and c.data.startswith("item:"), state="*")
    async def show_item_card(callback: types.CallbackQuery) -> None:
        await callback.answer()
        user = get_or_create_user(callback.from_user)
        _, raw_id = callback.data.split(":", 1)
        try:
            item_id = int(raw_id)
        except ValueError:
            return

        with db_session() as session:
            item = session.query(Item).get(item_id)

        if not item:
            await callback.message.edit_text("Эта вещь больше не найдена в базе (возможно, её удалили из таблицы).")
            return

        is_owner = bool(user.owner_handle and user.owner_handle.lower() == item.owner_handle.lower())
        deposit_text = "Залог обязателен" if item.deposit_required else "Без залога"
        text_lines = [
            f"<b>{_e(item.name)}</b>",
            "",
            _e(item.description) or "Описание не указано.",
            "",
            f"Цена/срок аренды: <b>{format_price(item.price_raw)}</b>",
            f"Район: <i>{_e(item.area or 'не указан')}</i>",
            f"Тип: <i>{_e(item.type or 'не указан')}</i>",
            "",
            deposit_text,
            "",
            f"Владелец: {_e(item.owner_handle)}",
        ]
        caption = "\n".join(text_lines)
        kb = item_actions_keyboard(
            item.id, is_owner=is_owner, owner_handle=item.owner_handle
        )
        if item.photo_url:
            try:
                await callback.message.delete()
                await callback.message.bot.send_photo(
                    callback.message.chat.id,
                    photo=item.photo_url,
                    caption=caption,
                    reply_markup=kb,
                    parse_mode="HTML",
                )
            except Exception:
                await callback.message.bot.send_message(
                    callback.message.chat.id,
                    caption,
                    reply_markup=kb,
                    parse_mode="HTML",
                )
        else:
            await callback.message.edit_text(
                caption,
                reply_markup=kb,
                parse_mode="HTML",
            )

