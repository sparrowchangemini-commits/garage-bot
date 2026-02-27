# Garage Bot — бот аренды вещей

Telegram-бот для аренды вещей комьюнити. Данные о вещах хранятся в Google Sheets и синхронизируются в локальную БД.

## Возможности

- **Поиск вещей** — по названию, фильтры по району, типу и владельцу
- **Бронирование** — ввод дат, подтверждение владельцем, подтверждение оплаты
- **Мои бронирования** — список броней арендатора, отмена, «Я оплатил»
- **Мои вещи** — список вещей владельца, подтверждение оплаты, написать арендатору
- **Напоминания об оплате** — T-24h, T-12h, T-2h до начала брони
- **Автоотмена** — неоплаченные брони отменяются в дату начала
- **Напоминания о возврате** — после отмены оплаченной брони арендатору

## Требования

- Python 3.11+
- Аккаунт Google Cloud с Service Account и доступом к Google Sheets API

## Установка

1. Клонируйте репозиторий и перейдите в каталог проекта.

2. Создайте виртуальное окружение и установите зависимости:

```bash
python -m venv .venv
.venv\Scripts\activate   # Windows
# или: source .venv/bin/activate   # Linux/macOS
pip install -r requirements.txt
```

3. Создайте файл `.env` в корне проекта:

```
BOT_TOKEN=ваш_токен_от_BotFather
GOOGLE_SPREADSHEET_ID=id_таблицы_google_sheets
GOOGLE_SERVICE_ACCOUNT_FILE=путь/к/google-service-account.json
GOOGLE_ITEMS_WORKSHEET_NAME=ALL
DATABASE_URL=sqlite:///garage_bot.db
ADMIN_IDS=
```

- **BOT_TOKEN** — токен Telegram-бота
- **GOOGLE_SPREADSHEET_ID** — ID таблицы (из URL: `docs.google.com/spreadsheets/d/ID/...`)
- **GOOGLE_SERVICE_ACCOUNT_FILE** — путь к JSON-ключу сервисного аккаунта
- **GOOGLE_ITEMS_WORKSHEET_NAME** — имя листа или `ALL` для всех листов (название листа = тип вещи)
- **DATABASE_URL** — URL БД (по умолчанию SQLite)
- **ADMIN_IDS** — через запятую (опционально)

4. Настройте Google Sheets:

- Разделите доступ к файлу с email сервисного аккаунта (из JSON)
- Структура листа: столбцы «Предмет», «Описание», «Цена/срок аренды», «Контакт» (ник владельца), «Район», «Комментарии», «Залог» и т.п.
- Для фото в карточке — столбец «Фото» или «Photo» с прямой ссылкой на изображение (например `https://example.com/image.jpg`). Для Google Drive: `https://drive.google.com/uc?export=view&id=FILE_ID`
- Название листа используется как тип вещи

## Запуск

```bash
python main.py
```

## Команды

- `/start` — главное меню
- `/sync_items` — ручная синхронизация вещей из Google Sheets

## Часовой пояс

По умолчанию: `Europe/Madrid`. Меняется в `bot/config.py` (BotConfig.timezone).
