"""Напоминания арендатору подтвердить возврат денег после отмены оплаченной брони."""
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram import types
from sqlalchemy import text

from . import db
from .models import Booking, BookingState


def ensure_item_photo_column() -> None:
    """Добавить колонку photo_url в items, если её нет (миграция)."""
    engine = db.engine
    if engine is None:
        return
    try:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE items ADD COLUMN photo_url VARCHAR(512)"))
            conn.commit()
    except Exception as e:
        if "duplicate" not in str(e).lower() and "already exists" not in str(e).lower():
            raise


def ensure_refund_columns() -> None:
    """Добавить колонки для возврата, если их нет (миграция)."""
    engine = db.engine
    if engine is None:
        return
    for col in ("refund_confirmed_at", "last_refund_reminder_at"):
        try:
            with engine.connect() as conn:
                conn.execute(text(f"ALTER TABLE bookings ADD COLUMN {col} DATETIME"))
                conn.commit()
        except Exception as e:
            if "duplicate" not in str(e).lower() and "already exists" not in str(e).lower():
                raise


async def send_refund_reminders(bot: Bot) -> int:
    """
    Отправить арендаторам напоминания подтвердить возврат денег.
    Возвращает количество отправленных напоминаний.
    """
    from .db import SessionLocal
    from sqlalchemy.orm import Session

    session: Session = SessionLocal()
    try:
        now = datetime.utcnow()
        # Брони: отменены арендатором, были оплачены, возврат не подтверждён
        # И last_reminder было больше 24ч назад (или null — первое напоминание)
        cutoff = now - timedelta(hours=24)

        rows = (
            session.query(Booking)
            .filter(
                Booking.state == BookingState.canceled_by_renter,
                Booking.paid_confirmed_at.isnot(None),
                Booking.refund_confirmed_at.is_(None),
            )
            .all()
        )

        sent = 0
        for b in rows:
            last = b.last_refund_reminder_at
            if last is None or last <= cutoff:
                item_name = b.item.name if b.item else "Вещь"
                dates_str = f"{b.start_date.strftime('%d.%m')}–{b.end_date.strftime('%d.%m')}"
                text_msg = (
                    f"Напоминание: вы отменили оплаченную бронь «{item_name}» ({dates_str}).\n\n"
                    "Подтвердите, пожалуйста, что владелец вернул вам деньги (и залог, если был)."
                )
                kb = types.InlineKeyboardMarkup()
                kb.add(
                    types.InlineKeyboardButton(
                        text="✅ Подтвердить возврат",
                        callback_data=f"renter_confirm_refund:{b.id}",
                    )
                )
                try:
                    await bot.send_message(b.renter_user_id, text_msg, reply_markup=kb)
                    b.last_refund_reminder_at = now
                    sent += 1
                except Exception:
                    pass

        session.commit()
        return sent
    finally:
        session.close()
