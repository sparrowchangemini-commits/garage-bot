"""Вспомогательные функции."""
import html
import re


def _e(s: str) -> str:
    """Экранировать HTML в пользовательских данных."""
    return html.escape(str(s) if s else "")


def format_price(raw: str) -> str:
    """Добавить знак € после первой цифры, если его ещё нет."""
    if not raw or "€" in raw:
        return raw or ""
    match = re.search(r"\d+(?:[.,]\d+)?", raw)
    if not match:
        return raw
    return raw[: match.end()] + "€" + raw[match.end() :]
