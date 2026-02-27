from typing import Tuple

from .config import load_settings
from .db import db_session, init_db
from .models import Item
from .sheets import SheetItem, fetch_items_from_sheet


def _upsert_item(sheet_item: SheetItem) -> None:
    with db_session() as session:
        existing: Item | None = (
            session.query(Item)
            .filter(Item.type == sheet_item.type, Item.sheet_row == sheet_item.sheet_row)
            .one_or_none()
        )
        if existing is None:
            existing = Item(sheet_row=sheet_item.sheet_row)
            session.add(existing)

        existing.name = sheet_item.name
        existing.description = sheet_item.description
        existing.price_raw = sheet_item.price_raw
        existing.owner_handle = sheet_item.owner_handle
        existing.area = sheet_item.area
        existing.type = sheet_item.type
        existing.comment = sheet_item.comment
        existing.deposit_required = sheet_item.deposit_required
        existing.photo_url = sheet_item.photo_url or None


def sync_items_from_google() -> Tuple[int, int]:
    """Синхронизировать вещи из таблицы в БД.

    Возвращает (count_items, count_rows), где:
    - count_items — сколько вещей сохранено в БД;
    - count_rows — сколько строк было в таблице (после фильтрации пустых).
    """
    settings = load_settings()
    init_db(settings.db.url)

    sheet_items = fetch_items_from_sheet(settings)
    for si in sheet_items:
        _upsert_item(si)

    return len(sheet_items), len(sheet_items)

