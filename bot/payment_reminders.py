"""Напоминания об оплате (T-24h, T-12h, T-2h) и автоотмена неоплаченных броней."""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from aiogram import Bot

from .db import db_session
from .models import Booking, BookingState, Notification, NotificationType


def _booking_start_utc(booking: Booking, tz_name: str = "Europe/Madrid") -> datetime:
    """Полночь даты начала брони в локальной tz, приведённая к naive UTC."""
    tz = ZoneInfo(tz_name)
    local_midnight = datetime.combine(booking.start_date, datetime.min.time(), tzinfo=tz)
    utc = local_midnight.astimezone(timezone.utc)
    return utc.replace(tzinfo=None)


def schedule_payment_notifications(booking_id: int) -> None:
    """Запланировать напоминания об оплате при подтверждении владельцем."""
    with db_session() as session:
        booking = session.query(Booking).get(booking_id)
        if not booking or booking.state != BookingState.confirmed_unpaid:
            return
        start_dt = _booking_start_utc(booking)
        now = datetime.utcnow()
        for ntype, hours in [
            (NotificationType.minus_24h, 24),
            (NotificationType.minus_12h, 12),
            (NotificationType.minus_2h, 2),
        ]:
            scheduled = start_dt - timedelta(hours=hours)
            if scheduled > now:
                existing = (
                    session.query(Notification)
                    .filter(
                        Notification.booking_id == booking_id,
                        Notification.type == ntype,
                    )
                    .first()
                )
                if not existing:
                    session.add(
                        Notification(
                            booking_id=booking_id,
                            type=ntype,
                            scheduled_for=scheduled,
                        )
                    )


async def run_payment_reminders(bot: Bot) -> int:
    """
    Отправить напоминания об оплате (T-24h, T-12h, T-2h).
    Вернуть количество отправленных.
    """
    sent = 0
    with db_session() as session:
        now = datetime.utcnow()
        due = (
            session.query(Notification)
            .filter(
                Notification.type.in_([
                    NotificationType.minus_24h,
                    NotificationType.minus_12h,
                    NotificationType.minus_2h,
                ]),
                Notification.sent == False,
                Notification.scheduled_for <= now,
            )
            .all()
        )
        for n in due:
            booking = session.query(Booking).get(n.booking_id)
            if not booking or booking.state != BookingState.confirmed_unpaid:
                n.sent = True
                continue
            item_name = booking.item.name if booking.item else "Вещь"
            hours_map = {
                NotificationType.minus_24h: "24",
                NotificationType.minus_12h: "12",
                NotificationType.minus_2h: "2",
            }
            h = hours_map.get(n.type, "?")
            text = (
                f"Напоминание: бронь «{item_name}» "
                f"({booking.start_date.strftime('%d.%m')}–{booking.end_date.strftime('%d.%m')}) "
                f"начинается через {h} ч. Не забудьте оплатить!"
            )
            try:
                await bot.send_message(booking.renter_user_id, text)
                n.sent = True
                n.sent_at = now
                sent += 1
            except Exception:
                pass
    return sent


async def auto_cancel_unpaid(bot: Bot) -> int:
    """
    Автоотмена неоплаченных броней, у которых дата начала уже прошла.
    Вернуть количество отменённых.
    """
    today = date.today()
    canceled = 0
    with db_session() as session:
        unpaid = (
            session.query(Booking)
            .filter(
                Booking.state == BookingState.confirmed_unpaid,
                Booking.start_date <= today,
            )
            .all()
        )
        for b in unpaid:
            b.state = BookingState.canceled_unpaid_timeout
            item_name = b.item.name if b.item else "Вещь"
            dates_str = f"{b.start_date.strftime('%d.%m')}–{b.end_date.strftime('%d.%m')}"
            try:
                await bot.send_message(
                    b.renter_user_id,
                    f"Бронь «{item_name}» ({dates_str}) отменена: оплата не подтверждена к дате начала.",
                )
            except Exception:
                pass
            if b.owner and b.owner.tg_id != b.renter_user_id:
                try:
                    await bot.send_message(
                        b.owner.tg_id,
                        f"Бронь «{item_name}» ({dates_str}) автоотменена: оплата не получена.",
                    )
                except Exception:
                    pass
            canceled += 1
    return canceled
