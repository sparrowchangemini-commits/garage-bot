"""Календарь для выбора дат бронирования."""
import calendar
from datetime import date

from aiogram import types


MONTHS_RU = [
    "", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]
WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def build_calendar_keyboard(
    year: int,
    month: int,
    min_date: date | None = None,
    max_date: date | None = None,
    prefix: str = "cal",
    one_day_btn: date | None = None,
    blocked_dates: set[date] | None = None,
) -> types.InlineKeyboardMarkup:
    """Строит inline-клавиатуру календаря на указанный месяц."""
    kb = types.InlineKeyboardMarkup(row_width=7)

    # Заголовок: месяц год, кнопки prev/next
    header = f"{MONTHS_RU[month]} {year}"
    kb.row(
        types.InlineKeyboardButton(text="◀", callback_data=f"{prefix}:nav:{year}:{month}:-1"),
        types.InlineKeyboardButton(text=header, callback_data=f"{prefix}:ignore"),
        types.InlineKeyboardButton(text="▶", callback_data=f"{prefix}:nav:{year}:{month}:1"),
    )
    # Дни недели
    kb.row(*[types.InlineKeyboardButton(text=w, callback_data=f"{prefix}:ignore") for w in WEEKDAYS])

    # Сетка дней (пн=0, вт=1, ...)
    cal = calendar.Calendar(firstweekday=0)  # Понедельник
    weeks = list(cal.monthdayscalendar(year, month))
    today = date.today()

    for week in weeks:
        row = []
        for day in week:
            if day == 0:
                row.append(types.InlineKeyboardButton(text=" ", callback_data=f"{prefix}:ignore"))
            else:
                d = date(year, month, day)
                # Недоступные (прошлые, бронь, за пределами диапазона) — крупная точка ●
                if d < today:
                    row.append(types.InlineKeyboardButton(text="●", callback_data=f"{prefix}:ignore"))
                elif blocked_dates and d in blocked_dates:
                    row.append(types.InlineKeyboardButton(text="●", callback_data=f"{prefix}:ignore"))
                elif min_date and d < min_date:
                    row.append(types.InlineKeyboardButton(text="●", callback_data=f"{prefix}:ignore"))
                elif max_date and d > max_date:
                    row.append(types.InlineKeyboardButton(text="●", callback_data=f"{prefix}:ignore"))
                else:
                    label = f"•{day}•" if d == today else str(day)
                    row.append(
                        types.InlineKeyboardButton(
                            text=label,
                            callback_data=f"{prefix}:sel:{year}:{month}:{day}",
                        )
                    )
        kb.row(*row)

    if one_day_btn:
        kb.add(
            types.InlineKeyboardButton(
                text=f"Один день ({one_day_btn.strftime('%d.%m')})",
                callback_data=f"{prefix}:sel:{one_day_btn.year}:{one_day_btn.month}:{one_day_btn.day}",
            )
        )

    return kb


def parse_calendar_callback(data: str) -> tuple[str, int, int, int] | None:
    """
    Парсит callback_data.
    Возвращает ("nav", y, m, delta) или ("sel", y, m, d) или None.
    """
    if not data or not data.startswith("cal:"):
        return None
    parts = data.split(":")
    if len(parts) < 2:
        return None
    action = parts[1]
    if action == "ignore":
        return None
    if action == "nav" and len(parts) >= 5:
        try:
            y, m, delta = int(parts[2]), int(parts[3]), int(parts[4])
            return ("nav", y, m, delta)
        except ValueError:
            return None
    if action == "sel" and len(parts) >= 5:
        try:
            y, m, d = int(parts[2]), int(parts[3]), int(parts[4])
            return ("sel", y, m, d)
        except ValueError:
            return None
    return None
