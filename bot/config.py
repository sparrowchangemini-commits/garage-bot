import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


_DOTENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=_DOTENV_PATH, override=False)


@dataclass
class BotConfig:
    token: str
    admin_ids: list[int]
    timezone: str = "Europe/Madrid"


@dataclass
class SheetsConfig:
    spreadsheet_id: str
    service_account_file: str
    items_worksheet_name: str = "Лист1"


@dataclass
class DatabaseConfig:
    url: str = "sqlite:///garage_bot.db"


@dataclass
class Settings:
    bot: BotConfig
    sheets: SheetsConfig
    db: DatabaseConfig


def _parse_admin_ids(raw: str | None) -> list[int]:
    if not raw:
        return []
    result: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            result.append(int(part))
        except ValueError:
            continue
    return result


def load_settings() -> Settings:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is not set in environment or .env")

    admin_ids = _parse_admin_ids(os.getenv("ADMIN_IDS"))

    spreadsheet_id = os.getenv("GOOGLE_SPREADSHEET_ID", "").strip()
    if not spreadsheet_id:
        raise RuntimeError("GOOGLE_SPREADSHEET_ID is not set")

    service_account_file = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "").strip()
    if not service_account_file:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_FILE is not set")

    items_ws_name = os.getenv("GOOGLE_ITEMS_WORKSHEET_NAME", "Лист1").strip() or "Лист1"

    db_url = os.getenv("DATABASE_URL", "sqlite:///garage_bot.db")

    return Settings(
        bot=BotConfig(token=token, admin_ids=admin_ids),
        sheets=SheetsConfig(
            spreadsheet_id=spreadsheet_id,
            service_account_file=service_account_file,
            items_worksheet_name=items_ws_name,
        ),
        db=DatabaseConfig(url=db_url),
    )

