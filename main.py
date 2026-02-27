from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.utils import executor
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.config import load_settings
from bot.db import Base, init_db
from bot.handlers_booking import register_booking_handlers
from bot.handlers_search import register_search_handlers
from bot.payment_reminders import auto_cancel_unpaid, run_payment_reminders
from bot.refund_reminders import ensure_item_photo_column, ensure_refund_columns, send_refund_reminders
from bot.sync_items import sync_items_from_google


async def on_startup(dispatcher: Dispatcher) -> None:
    settings = load_settings()
    engine = init_db(settings.db.url)
    Base.metadata.create_all(bind=engine)
    ensure_item_photo_column()
    ensure_refund_columns()

    scheduler = AsyncIOScheduler(timezone=settings.bot.timezone)
    scheduler.add_job(sync_items_from_google, "interval", minutes=10, id="sync_items_periodic")
    scheduler.add_job(
        send_refund_reminders,
        "interval",
        hours=24,
        id="refund_reminders",
        args=[dispatcher.bot],
    )
    scheduler.add_job(
        run_payment_reminders,
        "interval",
        minutes=15,
        id="payment_reminders",
        args=[dispatcher.bot],
    )
    scheduler.add_job(
        auto_cancel_unpaid,
        "interval",
        hours=1,
        id="auto_cancel_unpaid",
        args=[dispatcher.bot],
    )
    scheduler.start()


def register_service_handlers(dp: Dispatcher) -> None:
    @dp.message_handler(commands=["sync_items"], state="*")
    async def cmd_sync_items(message: types.Message, state) -> None:
        await message.answer("Запускаю синхронизацию с таблицей, это может занять несколько секунд...")
        try:
            count, _ = sync_items_from_google()
        except Exception as e:
            import traceback
            traceback.print_exc()
            await message.answer(f"Ошибка при синхронизации: {type(e).__name__}: {e}")
            return
        await message.answer(f"Синхронизация завершена. В БД сохранено вещей: {count}.")


def main() -> None:
    settings = load_settings()
    bot = Bot(token=settings.bot.token, parse_mode=types.ParseMode.HTML)
    storage = MemoryStorage()
    dp = Dispatcher(bot, storage=storage)

    register_service_handlers(dp)
    register_search_handlers(dp)
    register_booking_handlers(dp)

    executor.start_polling(dp, on_startup=on_startup)


if __name__ == "__main__":
    main()
