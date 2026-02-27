import calendar as cal_mod
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

from aiogram import Dispatcher, types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from sqlalchemy import and_, or_
from sqlalchemy.orm import joinedload

from .calendar_keyboard import build_calendar_keyboard, parse_calendar_callback
from .db import db_session
from .keyboards import items_list_keyboard
from .models import Booking, BookingState, Item, User
from .payment_reminders import schedule_payment_notifications
from .users import get_or_create_user
from .utils import format_price


class BookingStates(StatesGroup):
    waiting_for_dates = State()


@dataclass
class PendingBookingContext:
    item_id: int
    is_self_booking: bool = False


def _get_blocked_dates_for_item(item_id: int, year: int, month: int) -> set[date]:
    """Возвращает занятые даты для вещи в указанном месяце."""
    first = date(year, month, 1)
    last_day = cal_mod.monthrange(year, month)[1]
    last = date(year, month, last_day)
    with db_session() as session:
        bookings = (
            session.query(Booking)
            .filter(
                Booking.item_id == item_id,
                Booking.state.in_(
                    [
                        BookingState.pending_owner_confirm,
                        BookingState.confirmed_unpaid,
                        BookingState.paid_confirmed,
                    ]
                ),
                Booking.start_date <= last,
                Booking.end_date >= first,
            )
            .all()
        )
        result = set()
        for b in bookings:
            start = max(b.start_date, first)
            end = min(b.end_date, last)
            d = start
            while d <= end:
                result.add(d)
                d += timedelta(days=1)
        return result


async def _do_booking(
    state: FSMContext,
    message: types.Message,
    tg_user,
    ctx: PendingBookingContext,
    start_date: date,
    end_date: date,
) -> None:
    """Выполняет создание бронирования после выбора дат."""
    renter = get_or_create_user(tg_user)

    with db_session() as session:
        item = session.query(Item).get(ctx.item_id)
        if not item:
            await state.finish()
            await message.answer("Вещь больше не найдена в базе.")
            return

        overlapping = (
            session.query(Booking)
            .filter(
                Booking.item_id == item.id,
                Booking.state.in_(
                    [
                        BookingState.pending_owner_confirm,
                        BookingState.confirmed_unpaid,
                        BookingState.paid_confirmed,
                    ]
                ),
                or_(
                    and_(Booking.start_date <= start_date, Booking.end_date >= start_date),
                    and_(Booking.start_date <= end_date, Booking.end_date >= end_date),
                    and_(Booking.start_date >= start_date, Booking.end_date <= end_date),
                ),
            )
            .first()
        )

        if overlapping:
            await message.answer(
                "В эти даты вещь уже занята. Попробуйте выбрать другой диапазон дат.",
            )
            return

        if ctx.is_self_booking:
            booking = Booking(
                item_id=item.id,
                renter_user_id=renter.tg_id,
                owner_user_id=renter.tg_id,
                start_date=start_date,
                end_date=end_date,
                state=BookingState.paid_confirmed,
                paid_confirmed_at=datetime.utcnow(),
            )
            session.add(booking)
            await state.finish()
            await message.answer(
                f"Вы заблокировали даты <b>{item.name}</b>: "
                f"{start_date.strftime('%d.%m')}–{end_date.strftime('%d.%m')}.",
                parse_mode="HTML",
            )
            return

        owner_user: User | None = (
            session.query(User).filter(User.owner_handle == item.owner_handle).one_or_none()
        )

        booking = Booking(
            item_id=item.id,
            renter_user_id=renter.tg_id,
            owner_user_id=owner_user.tg_id if owner_user else renter.tg_id,
            start_date=start_date,
            end_date=end_date,
            state=BookingState.pending_owner_confirm,
        )
        session.add(booking)

    await state.finish()

    text_summary = (
        f"Вы хотите забронировать <b>{item.name}</b>\n"
        f"Даты: <b>{start_date.strftime('%d.%m')}–{end_date.strftime('%d.%m')}</b>\n"
        f"Цена: <b>{format_price(item.price_raw)}</b>\n"
        f"Район: {item.area or 'не указан'}\n"
        f"Владелец: {item.owner_handle}\n"
    )
    await message.answer(
        text_summary + "\nЗапрос на бронирование отправлен владельцу, ждём подтверждения.",
        parse_mode="HTML",
    )

    if owner_user and owner_user.tg_id != renter.tg_id:
        btns = types.InlineKeyboardMarkup()
        btns.add(
            types.InlineKeyboardButton(
                text="✅ Подтвердить бронь",
                callback_data=f"owner_confirm:{booking.id}",
            ),
            types.InlineKeyboardButton(
                text="❌ Отклонить бронь",
                callback_data=f"owner_decline:{booking.id}",
            ),
        )
        await message.bot.send_message(
            owner_user.tg_id,
            (
                f"Новый запрос на бронь от @{tg_user.username or tg_user.id}.\n\n"
                f"Вещь: {item.name}\n"
                f"Даты: {start_date.strftime('%d.%m')}–{end_date.strftime('%d.%m')}\n"
                f"Цена: {format_price(item.price_raw)}\n"
            ),
            reply_markup=btns,
        )
        schedule_payment_notifications(booking.id)
    else:
        await message.answer(
            "Владелец ещё не запускал бота, поэтому я не могу отправить ему запрос.\n"
            "Пока что свяжитесь с ним напрямую по нику из карточки вещи.",
        )


def parse_dates(text: str) -> Optional[tuple[date, date]]:
    text = text.strip()
    if "–" in text:
        parts = text.split("–", 1)
    elif "-" in text:
        parts = text.split("-", 1)
    else:
        parts = [text, text]

    try:
        start = datetime.strptime(parts[0].strip(), "%d.%m").date().replace(year=date.today().year)
        end = datetime.strptime(parts[1].strip(), "%d.%m").date().replace(year=date.today().year)
    except ValueError:
        return None

    if end < start:
        start, end = end, start
    return start, end


def register_booking_handlers(dp: Dispatcher) -> None:
    @dp.message_handler(lambda m: m.text and "Мои бронирования" in m.text, state="*")
    async def my_bookings(message: types.Message, state: FSMContext) -> None:
        await state.finish()
        user = get_or_create_user(message.from_user)

        today = date.today()
        with db_session() as session:
            bookings = (
                session.query(Booking)
                .filter(Booking.renter_user_id == user.tg_id)
                .order_by(Booking.start_date.asc())
                .all()
            )

            if not bookings:
                text_to_send = "У вас пока нет броней."
                confirmed_unpaid_list = []
                cancelable_list = []
            else:
                def state_label(state: BookingState) -> str:
                    return {
                        BookingState.pending_owner_confirm: "ожидает подтверждения владельца",
                        BookingState.confirmed_unpaid: "подтверждена, оплата не подтверждена",
                        BookingState.paid_confirmed: "подтверждена и оплачена",
                        BookingState.canceled_by_owner: "отменена владельцем",
                        BookingState.canceled_by_renter: "отменена вами",
                        BookingState.canceled_unpaid_timeout: "отменена из‑за неоплаты",
                    }.get(state, state.value)

                lines_upcoming: list[str] = []
                lines_history: list[str] = []

                for b in bookings:
                    item_name = b.item.name if b.item else "Вещь (удалена)"
                    line = (
                        f"{item_name} — {b.start_date.strftime('%d.%m')}–{b.end_date.strftime('%d.%m')} "
                        f"({state_label(b.state)})"
                    )
                    if b.end_date >= today and b.state not in {
                        BookingState.canceled_by_owner,
                        BookingState.canceled_by_renter,
                        BookingState.canceled_unpaid_timeout,
                    }:
                        lines_upcoming.append(line)
                    else:
                        lines_history.append(line)

                text_parts = []
                if lines_upcoming:
                    text_parts.append("<b>Текущие и будущие брони:</b>")
                    text_parts.extend(f"• {l}" for l in lines_upcoming)
                if lines_history:
                    if text_parts:
                        text_parts.append("")
                    text_parts.append("<b>История:</b>")
                    text_parts.extend(f"• {l}" for l in lines_history)

                text_to_send = "\n".join(text_parts)

                # Кнопки «Я оплатил» и «Отменить» для броней (с датами для различения)
                confirmed_unpaid_list = [
                    (b.id, (b.item.name if b.item else "Вещь"), b.start_date, b.end_date)
                    for b in bookings
                    if b.state == BookingState.confirmed_unpaid and b.end_date >= today
                ]
                cancelable_list = [
                    (b.id, (b.item.name if b.item else "Вещь"), b.start_date, b.end_date, b.state)
                    for b in bookings
                    if b.state
                    in (
                        BookingState.pending_owner_confirm,
                        BookingState.confirmed_unpaid,
                        BookingState.paid_confirmed,
                    )
                    and b.end_date >= today
                ]

        reply_markup = None
        if confirmed_unpaid_list or cancelable_list:
            kb = types.InlineKeyboardMarkup()
            for bid, iname, start_d, end_d in confirmed_unpaid_list:
                dates_str = f"{start_d.strftime('%d.%m')}–{end_d.strftime('%d.%m')}"
                kb.add(
                    types.InlineKeyboardButton(
                        text=f"💰 Я оплатил — {iname} {dates_str}",
                        callback_data=f"renter_paid:{bid}",
                    )
                )
            for bid, iname, start_d, end_d, _ in cancelable_list:
                dates_str = f"{start_d.strftime('%d.%m')}–{end_d.strftime('%d.%m')}"
                kb.add(
                    types.InlineKeyboardButton(
                        text=f"❌ Отменить бронь — {iname} {dates_str}",
                        callback_data=f"renter_cancel:{bid}",
                    )
                )
            reply_markup = kb

        await message.answer(text_to_send, parse_mode="HTML", reply_markup=reply_markup)

    @dp.message_handler(lambda m: m.text and "Мои вещи" in m.text, state="*")
    async def my_items(message: types.Message, state: FSMContext) -> None:
        await state.finish()
        user = get_or_create_user(message.from_user)

        if not user.owner_handle:
            await message.answer(
                "Похоже, вы ещё не указаны как владелец ни одной вещи в таблице "
                "(в столбце «Контакт» должен быть ваш @ник).",
            )
            return

        with db_session() as session:
            items = (
                session.query(Item)
                .filter(Item.owner_handle == user.owner_handle)
                .order_by(Item.name.asc())
                .all()
            )

        if not items:
            await message.answer(
                "В таблице нет вещей с вашим ником во столбце «Контакт». "
                "Проверьте, что ник совпадает с вашим Telegram @username.",
            )
            return

        kb_items = [(it.id, f"{it.name} · {format_price(it.price_raw)}") for it in items]
        await message.answer(
            "Нажмите на вещь, чтобы открыть карточку:",
            reply_markup=items_list_keyboard(kb_items),
        )

        # Брони, ожидающие подтверждения оплаты
        with db_session() as session:
            unpaid = (
                session.query(Booking)
                .options(joinedload(Booking.renter), joinedload(Booking.item))
                .filter(
                    Booking.owner_user_id == user.tg_id,
                    Booking.state == BookingState.confirmed_unpaid,
                    Booking.end_date >= date.today(),
                )
                .order_by(Booking.start_date.asc())
                .all()
            )

        if unpaid:
            pay_kb = types.InlineKeyboardMarkup()
            for b in unpaid:
                bid = b.id
                iname = (b.item.name if b.item else "Вещь")[:25]
                row_btns = [
                    types.InlineKeyboardButton(
                        text=f"✅ Оплата — {iname}",
                        callback_data=f"owner_paid:{bid}",
                    ),
                    types.InlineKeyboardButton(
                        text=f"❌ Отмена — {iname}",
                        callback_data=f"owner_cancel_unpaid:{bid}",
                    ),
                ]
                pay_kb.row(*row_btns)
                if b.renter and b.renter.tg_id != user.tg_id:
                    renter_handle = f"@{b.renter.username}" if b.renter.username else f"id{b.renter.tg_id}"
                    pay_kb.add(
                        types.InlineKeyboardButton(
                            text=f"💬 Написать арендатору ({renter_handle})",
                            url=f"tg://user?id={b.renter.tg_id}",
                        )
                    )
            await message.answer(
                "Брони, ожидающие подтверждения оплаты (нажмите, когда получите оплату):",
                reply_markup=pay_kb,
            )

    @dp.callback_query_handler(lambda c: c.data and c.data.startswith("item_bookings:"), state="*")
    async def handle_item_bookings(callback: types.CallbackQuery) -> None:
        """Показать все бронирования вещи (даты + арендатор)."""
        await callback.answer()
        _, raw_id = callback.data.split(":", 1)
        try:
            item_id = int(raw_id)
        except ValueError:
            return

        with db_session() as session:
            item = session.query(Item).get(item_id)
        if not item:
            await callback.message.answer("Эта вещь больше не найдена в базе.")
            return

        user = get_or_create_user(callback.from_user)
        if not user.owner_handle or user.owner_handle.lower() != item.owner_handle.lower():
            await callback.message.answer("Эта опция доступна только владельцу вещи.")
            return

        with db_session() as session:
            bookings = (
                session.query(Booking)
                .options(joinedload(Booking.renter))
                .filter(Booking.item_id == item_id)
                .order_by(Booking.start_date.desc())
                .all()
            )

        if not bookings:
            await callback.message.answer(f"У «{item.name}» пока нет бронирований.")
            return

        def _state_label(s: BookingState) -> str:
            labels = {
                BookingState.pending_owner_confirm: "ожидает подтверждения",
                BookingState.confirmed_unpaid: "ожидает оплаты",
                BookingState.paid_confirmed: "оплачена",
                BookingState.canceled_by_owner: "отменена владельцем",
                BookingState.canceled_by_renter: "отменена арендатором",
                BookingState.canceled_unpaid_timeout: "отменена (неоплата)",
            }
            return labels.get(s, str(s))

        lines = [f"<b>Бронирования «{item.name}»</b>", ""]
        for b in bookings:
            dates_str = f"{b.start_date.strftime('%d.%m')}–{b.end_date.strftime('%d.%m')}"
            renter_str = "—"
            if b.renter:
                renter_str = f"@{b.renter.username}" if b.renter.username else f"id{b.renter.tg_id}"
            state_str = _state_label(b.state)
            lines.append(f"• {dates_str} · {renter_str} · {state_str}")

        await callback.message.answer("\n".join(lines), parse_mode="HTML")

    @dp.callback_query_handler(lambda c: c.data and c.data.startswith("book:"), state="*")
    async def handle_book_start(callback: types.CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        _, raw_id = callback.data.split(":", 1)
        try:
            item_id = int(raw_id)
        except ValueError:
            return

        with db_session() as session:
            item = session.query(Item).get(item_id)
        if not item:
            await callback.message.answer("Эта вещь больше не найдена в базе.")
            return

        today = date.today()
        await state.update_data(
            pending_booking=PendingBookingContext(item_id=item_id, is_self_booking=False).__dict__,
            cal_step="start",
            cal_year=today.year,
            cal_month=today.month,
        )
        await BookingStates.waiting_for_dates.set()
        blocked = _get_blocked_dates_for_item(item_id, today.year, today.month)
        kb = build_calendar_keyboard(today.year, today.month, blocked_dates=blocked)
        await callback.message.answer(
            "Выберите <b>дату начала</b> аренды:",
            reply_markup=kb,
            parse_mode="HTML",
        )

    @dp.callback_query_handler(lambda c: c.data and c.data.startswith("selfbook:"), state="*")
    async def handle_self_book_start(callback: types.CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        _, raw_id = callback.data.split(":", 1)
        try:
            item_id = int(raw_id)
        except ValueError:
            return

        with db_session() as session:
            item = session.query(Item).get(item_id)
        if not item:
            await callback.message.answer("Эта вещь больше не найдена в базе.")
            return

        user = get_or_create_user(callback.from_user)
        if not user.owner_handle or user.owner_handle.lower() != item.owner_handle.lower():
            await callback.message.answer("Эта опция доступна только владельцу вещи.")
            return

        today = date.today()
        await state.update_data(
            pending_booking=PendingBookingContext(item_id=item_id, is_self_booking=True).__dict__,
            cal_step="start",
            cal_year=today.year,
            cal_month=today.month,
        )
        await BookingStates.waiting_for_dates.set()
        blocked = _get_blocked_dates_for_item(item_id, today.year, today.month)
        kb = build_calendar_keyboard(today.year, today.month, blocked_dates=blocked)
        await callback.message.answer(
            "Заблокировать даты как владелец. Выберите <b>дату начала</b>:",
            reply_markup=kb,
            parse_mode="HTML",
        )

    @dp.callback_query_handler(
        lambda c: c.data and c.data.startswith("cal:"),
        state=BookingStates.waiting_for_dates,
    )
    async def handle_calendar_callback(callback: types.CallbackQuery, state: FSMContext) -> None:
        parsed = parse_calendar_callback(callback.data)
        if not parsed:
            await callback.answer()
            return
        action, y, m, val = parsed[0], parsed[1], parsed[2], parsed[3]
        data = await state.get_data()
        ctx_raw = data.get("pending_booking")
        if not ctx_raw:
            await callback.answer()
            await state.finish()
            return
        ctx = PendingBookingContext(**ctx_raw)
        today = date.today()

        if action == "nav":
            delta = val
            new_month = m + delta
            new_year = y
            if new_month > 12:
                new_month = 1
                new_year += 1
            elif new_month < 1:
                new_month = 12
                new_year -= 1
            await state.update_data(cal_year=new_year, cal_month=new_month)
            start_str = data.get("cal_start_date")
            min_date = date.fromisoformat(start_str) if isinstance(start_str, str) else None
            blocked = _get_blocked_dates_for_item(ctx.item_id, new_year, new_month)
            kb = build_calendar_keyboard(
                new_year, new_month, min_date=min_date, one_day_btn=min_date, blocked_dates=blocked
            )
            caption = "Выберите <b>дату окончания</b>:" if min_date else "Выберите <b>дату начала</b>:"
            try:
                await callback.message.edit_reply_markup(reply_markup=kb)
            except Exception:
                await callback.message.edit_text(caption, reply_markup=kb, parse_mode="HTML")
            await callback.answer()
            return

        if action == "sel":
            sel_date = date(y, m, val)
            step = data.get("cal_step", "start")

            if step == "start":
                await state.update_data(cal_step="end", cal_start_date=sel_date.isoformat())
                blocked = _get_blocked_dates_for_item(ctx.item_id, y, m)
                kb = build_calendar_keyboard(y, m, min_date=sel_date, one_day_btn=sel_date, blocked_dates=blocked)
                await callback.message.edit_text(
                    f"Дата начала: <b>{sel_date.strftime('%d.%m')}</b>. Выберите <b>дату окончания</b>:",
                    reply_markup=kb,
                    parse_mode="HTML",
                )
                await callback.answer()
                return

            # step == "end"
            start_str = data.get("cal_start_date")
            start_date = date.fromisoformat(start_str) if isinstance(start_str, str) else start_str
            if not start_date or sel_date < start_date:
                await callback.answer("Дата окончания не может быть раньше начала", show_alert=True)
                return
            end_date = sel_date
            await callback.answer()
            await state.update_data(cal_step="start", cal_start_date=None)
            await _do_booking(state, callback.message, callback.from_user, ctx, start_date, end_date)

    @dp.message_handler(state=BookingStates.waiting_for_dates)
    async def handle_dates(message: types.Message, state: FSMContext) -> None:
        """Ручной ввод дат (ДД.ММ–ДД.ММ) как запасной вариант."""
        parsed = parse_dates(message.text or "")
        if not parsed:
            await message.answer(
                "Не удалось распознать даты. Используйте календарь выше или введите в формате ДД.ММ–ДД.ММ.",
            )
            return

        start_date, end_date = parsed

        data = await state.get_data()
        ctx_raw = data.get("pending_booking")
        if not ctx_raw:
            await state.finish()
            await message.answer("Контекст бронирования потерян, начните заново с карточки вещи.")
            return

        ctx = PendingBookingContext(**ctx_raw)
        await _do_booking(state, message, message.from_user, ctx, start_date, end_date)

    @dp.callback_query_handler(lambda c: c.data and c.data.startswith("owner_confirm:"), state="*")
    async def owner_confirm(callback: types.CallbackQuery) -> None:
        await callback.answer()
        _, raw_id = callback.data.split(":", 1)
        try:
            booking_id = int(raw_id)
        except ValueError:
            return

        with db_session() as session:
            booking = session.query(Booking).get(booking_id)
            if not booking:
                await callback.message.answer("Бронь не найдена.")
                return
            booking.state = BookingState.confirmed_unpaid
            item = booking.item
            renter = booking.renter

        await callback.message.edit_text("Вы подтвердили бронь. Ожидается оплата.")

        await callback.message.bot.send_message(
            renter.tg_id,
            (
                f"Владелец подтвердил вашу бронь:\n"
                f"Вещь: {item.name}\n"
                f"Даты: {booking.start_date.strftime('%d.%m')}–{booking.end_date.strftime('%d.%m')}\n"
                f"Цена: {format_price(item.price_raw)}\n"
                f"Свяжитесь с владельцем @{item.owner_handle.lstrip('@')} для оплаты."
            ),
        )

        # Владельцу сразу предлагаем подтвердить оплату, когда получит
        pay_kb = types.InlineKeyboardMarkup()
        pay_kb.add(
            types.InlineKeyboardButton(text="✅ Оплата получена", callback_data=f"owner_paid:{booking_id}"),
            types.InlineKeyboardButton(text="❌ Отменить бронь (оплаты нет)", callback_data=f"owner_cancel_unpaid:{booking_id}"),
        )
        await callback.message.bot.send_message(
            callback.from_user.id,
            f"Когда арендатор оплатит, нажмите «Оплата получена»:\n\n{item.name} — {booking.start_date.strftime('%d.%m')}–{booking.end_date.strftime('%d.%m')}",
            reply_markup=pay_kb,
        )
        schedule_payment_notifications(booking_id)

    @dp.callback_query_handler(lambda c: c.data and c.data.startswith("owner_paid:"), state="*")
    async def owner_paid(callback: types.CallbackQuery) -> None:
        await callback.answer()
        _, raw_id = callback.data.split(":", 1)
        try:
            booking_id = int(raw_id)
        except ValueError:
            return

        with db_session() as session:
            booking = session.query(Booking).get(booking_id)
            if not booking:
                return
            booking.state = BookingState.paid_confirmed
            booking.paid_confirmed_at = datetime.utcnow()
            item = booking.item
            renter = booking.renter

        await callback.message.edit_text("Оплата подтверждена.")

        await callback.message.bot.send_message(
            renter.tg_id,
            (
                f"Владелец подтвердил получение оплаты по брони:\n"
                f"Вещь: {item.name}\n"
                f"Даты: {booking.start_date.strftime('%d.%m')}–{booking.end_date.strftime('%d.%m')}."
            ),
        )

    @dp.callback_query_handler(lambda c: c.data and c.data.startswith("owner_cancel_unpaid:"), state="*")
    async def owner_cancel_unpaid(callback: types.CallbackQuery) -> None:
        await callback.answer()
        _, raw_id = callback.data.split(":", 1)
        try:
            booking_id = int(raw_id)
        except ValueError:
            return

        with db_session() as session:
            booking = session.query(Booking).get(booking_id)
            if not booking:
                return
            booking.state = BookingState.canceled_by_owner
            item = booking.item
            renter = booking.renter

        await callback.message.edit_text("Бронь отменена (оплата не получена).")

        await callback.message.bot.send_message(
            renter.tg_id,
            (
                f"Владелец отменил вашу бронь на {item.name} "
                f"({booking.start_date.strftime('%d.%m')}–{booking.end_date.strftime('%d.%m')})."
            ),
        )

    @dp.callback_query_handler(lambda c: c.data and c.data.startswith("renter_cancel:"), state="*")
    async def renter_cancel(callback: types.CallbackQuery) -> None:
        _, raw_id = callback.data.split(":", 1)
        try:
            booking_id = int(raw_id)
        except ValueError:
            await callback.answer()
            return

        with db_session() as session:
            booking = session.query(Booking).get(booking_id)
            if not booking or booking.renter_user_id != callback.from_user.id:
                await callback.answer()
                return
            if booking.state not in (
                BookingState.pending_owner_confirm,
                BookingState.confirmed_unpaid,
                BookingState.paid_confirmed,
            ):
                await callback.answer()
                return

            was_paid = booking.state == BookingState.paid_confirmed
            booking.state = BookingState.canceled_by_renter
            item_name = (booking.item.name if booking.item else "Вещь")
            item_deposit = bool(booking.item and booking.item.deposit_required)
            owner_tg_id = booking.owner.tg_id if booking.owner else None

        await callback.answer()
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await callback.message.answer("Бронь отменена.")

        if owner_tg_id and owner_tg_id != callback.from_user.id:
            dates_str = f"{booking.start_date.strftime('%d.%m')}–{booking.end_date.strftime('%d.%m')}"
            renter_handle = f"@{callback.from_user.username}" if callback.from_user.username else f"id{callback.from_user.id}"

            if was_paid:
                refund_hint = "Необходимо вернуть оплату"
                if item_deposit:
                    refund_hint += " и залог"
                refund_hint += "."
                owner_text = (
                    f"Арендатор отменил бронь на {item_name} ({dates_str}).\n\n"
                    f"{refund_hint}\nСвяжитесь с арендатором для возврата."
                )
            else:
                owner_text = f"Арендатор отменил бронь на {item_name} ({dates_str})."

            chat_btn = types.InlineKeyboardMarkup()
            chat_btn.add(
                types.InlineKeyboardButton(
                    text=f"💬 Написать арендатору ({renter_handle})",
                    url=f"tg://user?id={callback.from_user.id}",
                )
            )
            await callback.message.bot.send_message(
                owner_tg_id,
                owner_text,
                reply_markup=chat_btn,
            )

        if was_paid:
            renter_msg = (
                f"Вы отменили бронь «{item_name}» ({booking.start_date.strftime('%d.%m')}–{booking.end_date.strftime('%d.%m')}).\n\n"
                "Подтвердите, пожалуйста, когда владелец вернёт вам деньги (и залог, если был)."
            )
            renter_kb = types.InlineKeyboardMarkup()
            renter_kb.add(
                types.InlineKeyboardButton(
                    text="✅ Подтвердить возврат",
                    callback_data=f"renter_confirm_refund:{booking_id}",
                )
            )
            await callback.message.bot.send_message(
                callback.from_user.id,
                renter_msg,
                reply_markup=renter_kb,
            )
            with db_session() as s:
                b = s.query(Booking).get(booking_id)
                if b:
                    b.last_refund_reminder_at = datetime.utcnow()

    @dp.callback_query_handler(lambda c: c.data and c.data.startswith("renter_confirm_refund:"), state="*")
    async def renter_confirm_refund(callback: types.CallbackQuery) -> None:
        await callback.answer("Спасибо, возврат подтверждён.")
        _, raw_id = callback.data.split(":", 1)
        try:
            booking_id = int(raw_id)
        except ValueError:
            return

        with db_session() as session:
            booking = session.query(Booking).get(booking_id)
            if not booking or booking.renter_user_id != callback.from_user.id:
                return
            if booking.refund_confirmed_at:
                return
            booking.refund_confirmed_at = datetime.utcnow()

        try:
            await callback.message.edit_text("Вы подтвердили возврат денег. Спасибо!")
        except Exception:
            await callback.message.answer("Вы подтвердили возврат денег. Спасибо!")

    @dp.callback_query_handler(lambda c: c.data and c.data.startswith("renter_paid:"), state="*")
    async def renter_paid(callback: types.CallbackQuery) -> None:
        """Арендатор нажал «Я оплатил» — отправляем владельцу запрос на подтверждение."""
        await callback.answer("Сообщение владельцу отправлено.")
        _, raw_id = callback.data.split(":", 1)
        try:
            booking_id = int(raw_id)
        except ValueError:
            return

        with db_session() as session:
            booking = session.query(Booking).get(booking_id)
            if not booking or booking.state != BookingState.confirmed_unpaid:
                return
            item = booking.item
            owner = booking.owner

        pay_kb = types.InlineKeyboardMarkup()
        pay_kb.add(
            types.InlineKeyboardButton(text="✅ Оплата получена", callback_data=f"owner_paid:{booking_id}"),
            types.InlineKeyboardButton(text="❌ Отменить бронь (оплаты нет)", callback_data=f"owner_cancel_unpaid:{booking_id}"),
        )
        renter_handle = f"@{callback.from_user.username}" if callback.from_user.username else f"id{callback.from_user.id}"
        await callback.message.bot.send_message(
            owner.tg_id,
            f"Арендатор {renter_handle} сообщает, что оплатил. Подтвердите получение:\n\n{item.name} — {booking.start_date.strftime('%d.%m')}–{booking.end_date.strftime('%d.%m')}",
            reply_markup=pay_kb,
        )

    @dp.callback_query_handler(lambda c: c.data and c.data.startswith("owner_decline:"), state="*")
    async def owner_decline(callback: types.CallbackQuery) -> None:
        await callback.answer()
        _, raw_id = callback.data.split(":", 1)
        try:
            booking_id = int(raw_id)
        except ValueError:
            return

        with db_session() as session:
            booking = session.query(Booking).get(booking_id)
            if not booking:
                await callback.message.answer("Бронь не найдена.")
                return
            booking.state = BookingState.canceled_by_owner
            item = booking.item
            renter = booking.renter

        await callback.message.edit_text("Вы отклонили бронь.")

        await callback.message.bot.send_message(
            renter.tg_id,
            (
                f"Владелец отклонил вашу бронь:\n"
                f"Вещь: {item.name}\n"
                f"Даты: {booking.start_date.strftime('%d.%m')}–{booking.end_date.strftime('%d.%m')}"
            ),
        )

