import json
import os
import re
from datetime import datetime, timedelta
from typing import Any

import ollama

MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")

CHAT_SYSTEM_PROMPT = """Ты дружелюбный помощник Jarvis Study.
Отвечай по-русски, кратко и понятно.
Если вопрос про учебу, объясняй доступно.
Если вопрос про действие или план, предлагай ясные шаги."""

CLASSIFY_PROMPT = """Ты классифицируешь сообщение и возвращаешь только валидный JSON.

Есть ровно 3 категории:
- 1 = заметка, напоминание, личная задача пользователя
- 2 = вопрос, поиск, тема, факт, объяснение, информация
- 3 = домашнее задание для класса, которое учитель хочет задать ученикам

Категория 3 ТОЛЬКО если есть: номер или буква класса ("10 А", "11 Б" и т.п.) И предмет ИЛИ текст задания И дата выполнения.
Не выбирай 3 без явного указания класса.

ПРИМЕРЫ:
Вход: "напомни купить молоко завтра"
Ответ: {"category": 1}

Вход: "создай напоминание позвонить врачу 25 апреля"
Ответ: {"category": 1}

Вход: "объясни квантовую запутанность"
Ответ: {"category": 2}

Вход: "что такое фотосинтез"
Ответ: {"category": 2}

Вход: "задай домашнее задание для 10 А по математике параграф 304-307 на 25 апреля"
Ответ: {"category": 3}

Вход: "дз для 10 Б по физике задачи 227-232 на завтра"
Ответ: {"category": 3}

Вход: "для 11 А сочинение по литературе на 26 апреля"
Ответ: {"category": 3}

Отвечай СТРОГО: {"category": 1} или {"category": 2} или {"category": 3}"""

CLEAN_PROMPT = """Ты чистишь текст от служебных слов. Возвращай ТОЛЬКО валидный JSON.

Удали из текста слова-команды:
- создай, создать, запомни, запомнить
- напомни, напомнить, добавь, добавить
- заметку, заметка, напоминание, задачу, задача
- найди, найти, объясни, объяснить, расскажи

Оставь всё остальное без изменений — даты, числа, суть.

ПРИМЕРЫ:
Вход: "Создай напоминание собрать ядерный реактор 10 января 2026"
Выход: {"cleaned": "Собрать ядерный реактор 10 января 2026"}

Вход: "Запомни купить молоко завтра"
Выход: {"cleaned": "Купить молоко завтра"}

Вход: "Найди рецепт борща"
Выход: {"cleaned": "Рецепт борща"}

Вход: "Добавь задачу позвонить врачу 15 февраля 2026"
Выход: {"cleaned": "Позвонить врачу 15 февраля 2026"}

Отвечай СТРОГО: {"cleaned": "<очищенный текст>"}"""

EXTRACT_SEARCH_PROMPT = """Ты извлекаешь тему из уже очищенного текста. Возвращай ТОЛЬКО валидный JSON.

Текст уже без служебных слов — просто верни тему как есть.

ПРИМЕРЫ:
Вход: "Квантовая запутанность"
Выход: {"topic": "Квантовая запутанность"}

Вход: "Рецепт борща"
Выход: {"topic": "Рецепт борща"}

Отвечай СТРОГО: {"topic": "<тема>"}"""


def _note_prompt() -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    return f"""Ты извлекаешь данные из уже очищенного текста. Возвращай ТОЛЬКО валидный JSON.

Текст уже без служебных слов — просто раздели на задачу и дату.

ПРАВИЛА:
- task: что нужно сделать (без даты)
- date: дата в формате YYYY-MM-DD, если есть. Если нет — null
- Сегодня: {today}, завтра: {tomorrow}

ПРИМЕРЫ:
Вход: "Собрать ядерный реактор 10 января 2026"
Выход: {{"task": "Собрать ядерный реактор", "date": "2026-01-10"}}

Вход: "Купить молоко завтра"
Выход: {{"task": "Купить молоко", "date": "{tomorrow}"}}

Вход: "Позвонить врачу"
Выход: {{"task": "Позвонить врачу", "date": null}}

Отвечай СТРОГО: {{"task": "<суть>", "date": "<YYYY-MM-DD или null>"}}"""


def _teacher_homework_prompt() -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    return f"""Ты извлекаешь домашнее задание из сообщения учителя. Возвращай ТОЛЬКО валидный JSON.

Поля ответа:
- is_homework: true если это домашнее задание для класса, иначе false
- class_name: класс в виде "10 А", "10 Б", "11 А"
- subject: предмет, если он указан
- task: текст задания, что именно нужно сделать
- date: дата в формате YYYY-MM-DD

Сегодня: {today}
Завтра: {tomorrow}

ПРАВИЛА:
- Если в тексте "завтра", подставляй {tomorrow}
- Если "сегодня", подставляй {today}
- task должен содержать только суть ДЗ
- class_name должен быть нормализован, например "10 А"
- Если это не домашнее задание для класса, верни is_homework=false

ПРИМЕРЫ:
Вход: "задай домашнее задание для 10 А по математике на 2026-04-25: параграф 304-307"
Ответ: {{"is_homework": true, "class_name": "10 А", "subject": "математика", "task": "параграф 304-307", "date": "2026-04-25"}}

Вход: "дз для 10 Б по физике на завтра задачи 227-232"
Ответ: {{"is_homework": true, "class_name": "10 Б", "subject": "физика", "task": "задачи 227-232", "date": "{tomorrow}"}}

Вход: "для 11 А сочинение по литературе на 2026-04-26: перечитать главу"
Ответ: {{"is_homework": true, "class_name": "11 А", "subject": "литература", "task": "перечитать главу", "date": "2026-04-26"}}

Вход: "объясни закон Ома"
Ответ: {{"is_homework": false, "class_name": null, "subject": null, "task": null, "date": null}}

Отвечай СТРОГО:
{{"is_homework": true, "class_name": "<класс>", "subject": "<предмет или null>", "task": "<задание>", "date": "<YYYY-MM-DD>"}}"""


def _extract_json(raw: str) -> dict[str, Any]:
    match = re.search(r"\{.*?\}", raw, re.DOTALL)
    if not match:
        raise ValueError("Model response does not contain JSON object")
    return json.loads(match.group())


def _ollama_json(system_prompt: str, user_input: str) -> dict[str, Any]:
    response = ollama.chat(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_input},
        ],
        format="json",
        options={"temperature": 0.0},
    )
    raw = response["message"]["content"]
    return _extract_json(raw)


def _ollama_chat_free(messages: list[dict[str, str]]) -> str:
    response = ollama.chat(
        model=MODEL,
        messages=messages,
        options={"temperature": 0.4},
    )
    return (response["message"]["content"] or "").strip()


# ─────────────────────────────────────────
# Надёжная детекция ДЗ (без LLM)
# ─────────────────────────────────────────
def _looks_like_teacher_homework(user_input: str) -> bool:
    raw = str(user_input or "").strip().lower()
    if not raw:
        return False

    homework_markers = (
        "домашн",
        "дз ",
        " дз",
        "задание для",
        "задать",
        "задай",
        "создай дз",
        "домашнее задание",
    )
    has_marker = any(marker in raw for marker in homework_markers)

    # Есть ли класс вида "10 а", "11 б" и т.п.
    has_class = bool(re.search(r"\b\d{1,2}\s*[а-яёa-z]\b", raw))

    # Есть ли дата
    has_due_date = (
        bool(re.search(r"\d{4}-\d{2}-\d{2}", raw))
        or "завтра" in raw
        or "сегодня" in raw
        or bool(re.search(
            r"\d{1,2}\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)",
            raw
        ))
    )

    return has_marker or (has_class and has_due_date)


def _normalize_class_name(value: Any) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    match = re.search(r"(\d{1,2})\s*([А-ЯA-ZА-яa-z])", raw, re.IGNORECASE)
    if not match:
        return None
    number = match.group(1)
    letter = match.group(2).upper()
    latin_to_cyr = {"A": "А", "B": "Б", "V": "В", "G": "Г", "D": "Д", "E": "Е"}
    letter = latin_to_cyr.get(letter, letter)
    return f"{number} {letter}"


# ─────────────────────────────────────────
# ЭТАП 1: Классификация
# ─────────────────────────────────────────
def classify(user_input: str) -> int:
    # Быстрая детекция ДЗ без LLM — надёжнее маленьких моделей
    if _looks_like_teacher_homework(user_input):
        return 3

    try:
        parsed = _ollama_json(CLASSIFY_PROMPT, user_input)
        category = int(parsed.get("category", 2))
        if category in (1, 2, 3):
            return category
    except Exception:
        pass

    return 2


# ─────────────────────────────────────────
# ЭТАП 1.5: Очистка
# ─────────────────────────────────────────
def clean_input(user_input: str) -> str:
    parsed = _ollama_json(CLEAN_PROMPT, user_input)
    cleaned = str(parsed.get("cleaned", user_input)).strip()
    return cleaned or user_input.strip()


# ─────────────────────────────────────────
# ЭТАП 2а: Извлечение для ЗАМЕТКИ
# ─────────────────────────────────────────
def extract_note(cleaned_input: str) -> dict[str, Any]:
    parsed = _ollama_json(_note_prompt(), cleaned_input)
    task = str(parsed.get("task", cleaned_input)).strip() or cleaned_input
    date = parsed.get("date")
    if date in ("", "null"):
        date = None
    return {"task": task, "date": date}


def extract_teacher_homework(user_input: str) -> dict[str, Any]:
    normalized = user_input.strip()
    if not normalized:
        return {"is_homework": False, "class_name": None, "subject": None, "task": None, "date": None}

    try:
        parsed = _ollama_json(_teacher_homework_prompt(), normalized)
    except Exception:
        parsed = {}

    class_name = _normalize_class_name(parsed.get("class_name")) or _normalize_class_name(normalized)
    subject = str(parsed.get("subject") or "").strip() or None
    task = str(parsed.get("task") or "").strip() or None
    date = parsed.get("date")
    if date in ("", "null", None):
        date = None

    # Если LLM не дал дату — извлекаем из текста регулярками
    if not date:
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        today_str = datetime.now().strftime("%Y-%m-%d")
        low = normalized.lower()
        if "завтра" in low:
            date = tomorrow
        elif "сегодня" in low:
            date = today_str
        else:
            m = re.search(r"(\d{4}-\d{2}-\d{2})", normalized)
            if m:
                date = m.group(1)

    # Если задание не извлечено — пробуем через note
    if not task:
        try:
            cleaned = clean_input(normalized)
            note_data = extract_note(cleaned)
            task = note_data.get("task") or normalized
            if not date:
                date = note_data.get("date")
        except Exception:
            task = normalized

    is_homework = _looks_like_teacher_homework(normalized) or bool(parsed.get("is_homework")) or bool(class_name and task and date)

    return {
        "is_homework": is_homework,
        "class_name": class_name,
        "subject": subject,
        "task": task,
        "date": date,
    }


# ─────────────────────────────────────────
# ЭТАП 2б: Извлечение для ПОИСКА
# ─────────────────────────────────────────
def extract_search(cleaned_input: str) -> dict[str, Any]:
    parsed = _ollama_json(EXTRACT_SEARCH_PROMPT, cleaned_input)
    topic = str(parsed.get("topic", cleaned_input)).strip() or cleaned_input
    return {"topic": topic}


# ─────────────────────────────────────────
# ДИАЛОГ (чат)
# ─────────────────────────────────────────
def chat_reply(messages: list[dict[str, str]]) -> str:
    prepared = [{"role": "system", "content": CHAT_SYSTEM_PROMPT}, *messages]
    return _ollama_chat_free(prepared)


# ─────────────────────────────────────────
# ГЛАВНАЯ ФУНКЦИЯ
# ─────────────────────────────────────────
def smart_processor(user_input: str) -> dict[str, Any]:
    normalized = user_input.strip()
    if not normalized:
        return {"category": 1, "task": "", "date": None}

    try:
        category = classify(normalized)

        if category == 3:
            data = extract_teacher_homework(normalized)
            return {
                "category": 3,
                "class_name": data.get("class_name"),
                "subject": data.get("subject"),
                "task": data.get("task"),
                "date": data.get("date"),
            }

        cleaned = clean_input(normalized)

        if category == 1:
            data = extract_note(cleaned)
            return {
                "category": 1,
                "task": data.get("task", cleaned),
                "date": data.get("date", None),
            }

        data = extract_search(cleaned)
        return {
            "category": 2,
            "topic": data.get("topic", cleaned),
        }
    except Exception:
        return {"category": 2, "topic": normalized}
