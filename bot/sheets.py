from dataclasses import dataclass
from typing import Iterable, List, Optional

import gspread

from .config import Settings


@dataclass
class SheetItem:
    sheet_row: int
    name: str
    description: str
    price_raw: str
    owner_handle: str
    area: str
    type: str
    comment: str
    deposit_required: bool
    photo_url: str


def _to_bool(value: str) -> bool:
    v = (value or "").strip().lower()
    return v in {"1", "да", "yes", "true", "y", "д", "true/да"}


def _parse_worksheet(ws, default_type: str) -> List[SheetItem]:
    rows: Iterable[list[str]] = ws.get_all_values()
    if not rows:
        return []

    header = [h.strip() for h in rows[0]]

    def col_index(names: list[str]) -> Optional[int]:
        for name in names:
            if name in header:
                return header.index(name)
        return None

    idx_name = col_index(["Предмет", "Название", "Item"])
    idx_desc = col_index(["Описание", "Description"])
    idx_price = col_index(["Цена/срок аренды", "Цена", "Price"])
    idx_contact = col_index(["Контакт", "Телеграм", "Telegram", "Owner"])
    idx_area = col_index(["Район", "Area"])
    idx_comment = col_index(["Комментарии", "Комментарий", "Comment"])
    idx_deposit = col_index(["Залог", "Залог обязателен", "Deposit"])
    idx_photo = col_index(["Фото", "Photo", "Изображение"])

    items: List[SheetItem] = []
    for i, row in enumerate(rows[1:], start=2):  # данные начинаются со 2-й строки
        def get(idx: Optional[int]) -> str:
            return row[idx] if idx is not None and idx < len(row) else ""

        name = get(idx_name).strip()
        if not name:
            continue

        raw_owner = get(idx_contact).strip()
        if not raw_owner:
            continue

        # нормализуем ник владельца: добавляем @ при необходимости и приводим к нижнему регистру
        if raw_owner.startswith("@"):
            owner_handle = raw_owner.lower()
        else:
            owner_handle = ("@" + raw_owner).lower()

        raw_deposit = get(idx_deposit)
        comment = get(idx_comment)

        # 1) Явный столбец "Залог" / булево значение
        deposit_required = _to_bool(raw_deposit)

        # 2) Если явного булева нет, но в комментарии есть слово "залог" — считаем, что залог есть
        if not deposit_required and (comment or "").strip():
            if "залог" in comment.lower():
                deposit_required = True

        photo_raw = get(idx_photo).strip()
        photo_url = photo_raw if photo_raw.startswith("http") else ""

        items.append(
            SheetItem(
                sheet_row=i,
                name=name,
                description=get(idx_desc),
                price_raw=get(idx_price),
                owner_handle=owner_handle,
                area=get(idx_area),
                type=default_type,  # тип = название листа
                comment=comment,
                deposit_required=deposit_required,
                photo_url=photo_url,
            )
        )

    return items


def fetch_items_from_sheet(settings: Settings) -> List[SheetItem]:
    """Прочитать все вещи из Google Sheets и вернуть как список SheetItem.

    Если в настройке GOOGLE_ITEMS_WORKSHEET_NAME указано имя листа,
    берём только его. Если значение пустое, 'ALL' или '*', обходим все листы.
    """
    gc = gspread.service_account(filename=settings.sheets.service_account_file)
    sh = gc.open_by_key(settings.sheets.spreadsheet_id)

    ws_name = settings.sheets.items_worksheet_name
    if ws_name and ws_name not in {"ALL", "all", "*"}:
        worksheets = [sh.worksheet(ws_name)]
    else:
        worksheets = sh.worksheets()

    items: List[SheetItem] = []
    for ws in worksheets:
        items.extend(_parse_worksheet(ws, default_type=ws.title))

    return items

