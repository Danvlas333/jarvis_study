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

Есть ровно 4 категории:
- 1 = заметка, напоминание, личная задача пользователя
- 2 = вопрос, поиск, тема, факт, объяснение, информация
- 3 = домашнее задание для класса, которое учитель хочет задать ученикам
- 4 = анализ, планирование, разбор данных пользователя: например распланировать день, понять за что взяться сначала, проанализировать заметки/ДЗ/оценки

Категория 3 выбирается только если это именно выдача домашнего задания классу.
Обычно в таком сообщении есть:
- класс: "10 А", "10 Б", "11 А"
- дата: "2026-04-25", "завтра", "25 апреля"
- предмет или сам текст задания

Не путай категорию 3 с заметкой. Если пользователь пишет:
- "напомни мне..."
- "создай заметку..."
- "запомни..."
это категория 1, даже если там есть дата.

Не путай категорию 3 с поиском. Если пользователь просит:
- "объясни..."
- "что такое..."
- "найди..."
это категория 2.

Категория 4 выбирается, если пользователь просит:
- "распланируй мне день"
- "проанализируй мои дела"
- "скажи, что сделать сначала"
- "составь план по моим заметкам и дз"
- "посмотри мои оценки и помоги распределить нагрузку"

Если пользователь хочет именно новый план или анализ своих данных, это категория 4, а не категория 2.

ПРИМЕРЫ:
Вход: "напомни купить молоко завтра"
Ответ: {"category": 1}

Вход: "создай напоминание позвонить врачу 25 апреля"
Ответ: {"category": 1}

Вход: "объясни квантовую запутанность"
Ответ: {"category": 2}

Вход: "что такое фотосинтез"
Ответ: {"category": 2}

Вход: "Создай ДЗ для 10 А на 2026-04-25 по геометрии: решить №304-307"
Ответ: {"category": 3}

Вход: "задай домашнее задание для 10 А по математике параграф 304-307 на 25 апреля"
Ответ: {"category": 3}

Вход: "дз для 10 Б по физике задачи 227-232 на завтра"
Ответ: {"category": 3}

Вход: "для 11 А сочинение по литературе на 26 апреля"
Ответ: {"category": 3}

Вход: "распланируй мне день на завтра"
Ответ: {"category": 4}

Вход: "проанализируй мои заметки и дз и скажи что делать сначала"
Ответ: {"category": 4}

Отвечай СТРОГО: {"category": 1} или {"category": 2} или {"category": 3} или {"category": 4}"""

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

ANALYSIS_SCOPE_PROMPT = """Ты определяешь, что именно нужно анализировать для учебного помощника. Возвращай ТОЛЬКО валидный JSON.

Поля ответа:
- scope: массив из значений "notes", "homework", "grades", "performance"
- plan_date: дата в формате YYYY-MM-DD, если пользователь просит план на конкретный день. Иначе null
- focus: коротко, чего хочет пользователь

Важно:
- ты на этом шаге только определяешь, какие данные нужны для ответа
- ты не получаешь сами данные пользователя
- ты не отвечаешь на вопрос пользователя окончательно
- после твоего ответа код сам достанет нужные данные и передаст их в следующий шаг анализа

Правила:
- если пользователь пишет "на завтра", подставляй завтрашнюю дату
- если пользователь пишет "на сегодня", подставляй сегодняшнюю дату
- если неясно, что анализировать, выбирай все источники
- если пользователь явно упомянул заметки/напоминания, включай "notes"
- если пользователь явно упомянул дз/домашку/уроки, включай "homework"
- если пользователь явно упомянул оценки/баллы/успеваемость, включай "grades"
- если пользователь просит общий учебный план на день, обычно полезны "homework", "notes", "grades", "performance"

Сегодня: {today}
Завтра: {tomorrow}

ПРИМЕРЫ:
Вход: "распланируй мне день на завтра"
Ответ: {{"scope": ["notes", "homework", "grades", "performance"], "plan_date": "{tomorrow}", "focus": "распланировать день на завтра"}}

Вход: "проанализируй мои заметки и напоминания"
Ответ: {{"scope": ["notes"], "plan_date": null, "focus": "проанализировать заметки и напоминания"}}

Вход: "посмотри мои оценки и домашку"
Ответ: {{"scope": ["homework", "grades"], "plan_date": null, "focus": "проанализировать домашку и оценки"}}

Отвечай СТРОГО:
{{"scope": ["notes"], "plan_date": null, "focus": "<цель пользователя>"}}"""

ANALYSIS_REPLY_PROMPT = """Ты учебный помощник Jarvis Study. На основе запроса пользователя и его данных составь полезный план действий.

Правила ответа:
- отвечай по-русски
- будь конкретным и практичным
- данные уже были отобраны кодом, используй только переданный контекст
- если есть срочные или просроченные дела, скажи о них в начале
- если пользователь просит распланировать день, выстрой порядок: сначала сложное/срочное, потом среднее, потом легкое
- если данных мало, честно скажи об этом, но все равно предложи разумный план
- не выдумывай данные, опирайся только на переданный контекст
- ответ должен быть в обычном человеческом виде для чата, без JSON
- если видишь слабые оценки, мягко укажи, каким предметам уделить внимание
"""


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
    return f"""Ты извлекаешь домашнее задание из сообщения учителя. Возвращай только JSON.

Поля ответа:
- is_homework: true если это домашнее задание для класса, иначе false
- class_name: класс строго в виде "10 А", "10 Б", "11 А"
- subject: предмет или null
- task: только само задание, без служебных слов
- date: дата строго в формате YYYY-MM-DD или null
- points_value: ценность задания, если не указана -> 1

Сегодня: {today}
Завтра: {tomorrow}

Правила:
- Если есть класс, дата и формулировка задания, считай это домашним заданием
- Нормализуй класс: "10А", "10 а", "10-А" -> "10 А"
- Если есть "завтра", подставляй {tomorrow}
- Если есть "сегодня", подставляй {today}
- Если предмет написан без слова "по", все равно извлекай его
- Не включай в task слова "создай", "дз", "задание", "для 10 А", "на завтра", "по геометрии"
- Короткие форматы тоже являются ДЗ:
  "10А геометрия на завтра №304-307"
  "10 Б физика задачи 227-232 на завтра"
  "11А литература перечитать главу к 2026-04-26"
- Если это не задание для класса, верни is_homework=false

Примеры:
Вход: "10А геометрия на завтра №304-307"
Ответ: {{"is_homework": true, "class_name": "10 А", "subject": "геометрия", "task": "№304-307", "date": "{tomorrow}", "points_value": 1}}

Вход: "создай дз для 10 А на завтра по алгебре: решить №12-15, ценность 3"
Ответ: {{"is_homework": true, "class_name": "10 А", "subject": "алгебра", "task": "решить №12-15", "date": "{tomorrow}", "points_value": 3}}

Вход: "для 11А литература перечитать главу к 2026-04-26"
Ответ: {{"is_homework": true, "class_name": "11 А", "subject": "литература", "task": "перечитать главу", "date": "2026-04-26", "points_value": 1}}

Вход: "объясни закон Ома"
Ответ: {{"is_homework": false, "class_name": null, "subject": null, "task": null, "date": null, "points_value": 1}}

Отвечай строго так:
{{"is_homework": true, "class_name": "<класс>", "subject": "<предмет или null>", "task": "<задание>", "date": "<YYYY-MM-DD или null>", "points_value": 1}}"""

def _analysis_scope_prompt() -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    return ANALYSIS_SCOPE_PROMPT.format(today=today, tomorrow=tomorrow)


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
        "урок",
    )
    has_marker = any(marker in raw for marker in homework_markers)
    has_class = bool(re.search(r"\b\d{1,2}\s*[- ]?\s*[а-яёa-z]\b", raw))
    has_due_date = (
        bool(re.search(r"\d{4}-\d{2}-\d{2}", raw))
        or "завтра" in raw
        or "сегодня" in raw
        or bool(re.search(r"\d{1,2}\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)", raw))
    )
    has_subject = bool(re.search(r"\b(алгебра|геометрия|математика|физика|химия|биология|история|литература|информатика|английский\s+язык|обж|география)\b", raw))
    has_task_shape = bool(re.search(r"(№\s*\d+|упр\.?\s*\d+|задач|параграф|стр\.?\s*\d+|решить|прочитать|перечитать|выучить|подготовить)", raw))

    return has_marker or (has_class and (has_due_date or has_subject) and has_task_shape)

def _looks_like_note(user_input: str) -> bool:
    raw = str(user_input or "").strip().lower()
    if not raw:
        return False

    note_markers = (
        "напомни",
        "напомин",
        "заметк",
        "запомни",
        "добавь задачу",
        "добавь замет",
        "создай напомин",
        "создай замет",
        "позвонить",
        "купить",
        "сделать",
    )
    return any(marker in raw for marker in note_markers)


def _looks_like_analysis(user_input: str) -> bool:
    raw = str(user_input or "").strip().lower()
    if not raw:
        return False

    analysis_markers = (
        "распланируй",
        "спланируй",
        "составь план",
        "план на",
        "анализ",
        "проанализируй",
        "разбери",
        "что делать сначала",
        "что делать вначале",
        "в каком порядке",
        "мой день",
        "мои оценки",
        "мои заметки",
        "мои дела",
        "мое дз",
        "мою домашку",
    )
    if any(marker in raw for marker in analysis_markers):
        return True

    # Более мягкая эвристика на случай опечаток вроде "проананлизируй мои оценки".
    has_analysis_intent = (
        bool(re.search(r"анали[зс]", raw))
        or bool(re.search(r"проан[а-я]*лиз", raw))
        or bool(re.search(r"расплан", raw))
        or bool(re.search(r"спланир", raw))
        or "план" in raw
    )
    has_user_data_target = any(
        marker in raw
        for marker in (
            "оцен",
            "успева",
            "дз",
            "домаш",
            "замет",
            "напомин",
            "дела",
            "день",
        )
    )
    return has_analysis_intent and has_user_data_target


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


def _extract_due_date(value: str) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None

    low = raw.lower()
    if "завтра" in low:
        return (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    if "сегодня" in low:
        return datetime.now().strftime("%Y-%m-%d")

    exact = re.search(r"(\d{4}-\d{2}-\d{2})", raw)
    if exact:
        return exact.group(1)

    month_map = {
        "января": 1, "февраля": 2, "марта": 3, "апреля": 4,
        "мая": 5, "июня": 6, "июля": 7, "августа": 8,
        "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
    }
    month_match = re.search(
        r"(\d{1,2})\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)(?:\s+(\d{4}))?",
        low,
    )
    if month_match:
        day = int(month_match.group(1))
        month = month_map[month_match.group(2)]
        year = int(month_match.group(3) or datetime.now().year)
        return datetime(year, month, day).strftime("%Y-%m-%d")

    return None


def _extract_subject(raw: str) -> str | None:
    low = str(raw or "").lower()
    match = re.search(r"\b??\s+([?-??\- ]+?)(?=[:;,]|\s+??\b|\s+?\b|\s\d{4}-\d{2}-\d{2}|$)", low)
    if match:
        return match.group(1).strip(" .,:;")

    class_match = re.search(r"\b\d{1,2}\s*[- ]?\s*[?-??a-z]\b\s+([?-??\- ]+?)(?=\s+??\b|\s+?\b|\s\d{4}-\d{2}-\d{2}\b|:|,|;|$)", low)
    if class_match:
        candidate = class_match.group(1).strip(" .,:;")
        if candidate and len(candidate.split()) <= 3:
            return candidate
    return None

def _extract_homework_task(raw: str, class_name: str | None, subject: str | None, date_value: str | None) -> str | None:
    text = str(raw or "").strip()
    if not text:
        return None

    if ":" in text:
        after_colon = text.split(":", 1)[1].strip()
        if after_colon:
            return after_colon

    cleaned = text
    for pattern in (
        r"(?i)\b??????\b",
        r"(?i)\b???????\b",
        r"(?i)\b?????\b",
        r"(?i)\b???????? ???????\b",
        r"(?i)\b??\b",
        r"(?i)\b???\b",
        r"(?i)\b?\b",
        r"(?i)\b??\b",
    ):
        cleaned = re.sub(pattern, "", cleaned)

    if class_name:
        cleaned = re.sub(re.escape(class_name), "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(re.escape(class_name.replace(" ", "")), "", cleaned, flags=re.IGNORECASE)
    if subject:
        cleaned = re.sub(rf"(?i)\b??\s+{re.escape(subject)}\b", "", cleaned)
        cleaned = re.sub(rf"(?i)\b{re.escape(subject)}\b", "", cleaned)

    cleaned = re.sub(r"\d{4}-\d{2}-\d{2}", "", cleaned)
    cleaned = re.sub(r"(?i)\b(???????|??????)\b", "", cleaned)
    cleaned = re.sub(r"(?i)\b\d{1,2}\s+(??????|???????|?????|??????|???|????|????|???????|????????|???????|??????|???????)(\s+\d{4})?\b", "", cleaned)
    cleaned = re.sub(r"(?i)\b(???????|?????????|??????????|??????|?????|????????|???????|??????????|???????????|??????????\s+????|???|?????????)\b", "", cleaned)
    cleaned = re.sub(r"(?i)\b(????????|?????????)\s*\d+\b", "", cleaned)
    cleaned = re.sub(r"(?i)\b\d+\s*???[?-?]*\b", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,:;")
    return cleaned or None

def _extract_points_value(raw: str) -> int:
    text = str(raw or "").strip().lower()
    if not text:
        return 1

    patterns = (
        r"ценност[ьяи]*\s*(\d+)",
        r"стоимост[ьяи]*\s*(\d+)",
        r"(\d+)\s*очк",
        r"на\s*(\d+)\s*балл",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            try:
                return max(1, int(match.group(1)))
            except (TypeError, ValueError):
                return 1
    return 1


def _parse_teacher_homework_without_llm(user_input: str) -> dict[str, Any]:
    normalized = str(user_input or "").strip()
    class_name = _normalize_class_name(normalized)
    date_value = _extract_due_date(normalized)
    subject = _extract_subject(normalized)
    task = _extract_homework_task(normalized, class_name, subject, date_value)
    points_value = _extract_points_value(normalized)
    has_homework_intent = _looks_like_teacher_homework(normalized)
    is_homework = bool(class_name and task and (date_value or has_homework_intent) and has_homework_intent)
    return {
        "is_homework": is_homework,
        "class_name": class_name,
        "subject": subject,
        "task": task,
        "date": date_value,
        "points_value": points_value,
    }

# ─────────────────────────────────────────
# ЭТАП 1: Классификация
# ─────────────────────────────────────────
def classify(user_input: str) -> int:
    try:
        parsed = _ollama_json(CLASSIFY_PROMPT, user_input)
        category = int(parsed.get("category", 2))
        if category in (1, 2, 3, 4):
            if category == 2 and _looks_like_note(user_input) and not _looks_like_teacher_homework(user_input):
                return 1
            if category == 2 and _looks_like_analysis(user_input):
                return 4
            return category
    except Exception:
        pass

    # Fallback, если модель не ответила или ответила плохо.
    if _looks_like_analysis(user_input):
        return 4
    if _looks_like_teacher_homework(user_input):
        return 3
    if _looks_like_note(user_input):
        return 1

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
        return {"is_homework": False, "class_name": None, "subject": None, "task": None, "date": None, "points_value": 1}

    parsed_fast = _parse_teacher_homework_without_llm(normalized)

    try:
        parsed = _ollama_json(_teacher_homework_prompt(), normalized)
    except Exception:
        parsed = {}

    class_name = _normalize_class_name(parsed.get("class_name")) or _normalize_class_name(normalized)
    subject = str(parsed.get("subject") or "").strip() or None
    task = str(parsed.get("task") or "").strip() or None
    try:
        points_value = max(1, int(parsed.get("points_value", 1) or 1))
    except (TypeError, ValueError):
        points_value = 1
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

    # Если задание не извлечено — пробуем быстрым правилом и note
    if not task:
        task = parsed_fast.get("task")
    if not subject:
        subject = parsed_fast.get("subject")
    if not date:
        date = parsed_fast.get("date")
    if not points_value:
        points_value = int(parsed_fast.get("points_value") or 1)
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

    if not is_homework and parsed_fast.get("is_homework"):
        return parsed_fast

    return {
        "is_homework": is_homework,
        "class_name": class_name,
        "subject": subject,
        "task": task,
        "date": date,
        "points_value": points_value or int(parsed_fast.get("points_value") or 1),
    }


# ─────────────────────────────────────────
# ЭТАП 2б: Извлечение для ПОИСКА
# ─────────────────────────────────────────
def extract_search(cleaned_input: str) -> dict[str, Any]:
    parsed = _ollama_json(EXTRACT_SEARCH_PROMPT, cleaned_input)
    topic = str(parsed.get("topic", cleaned_input)).strip() or cleaned_input
    return {"topic": topic}


def extract_analysis_scope(user_input: str) -> dict[str, Any]:
    normalized = str(user_input or "").strip()
    default_scope = ["notes", "homework", "grades", "performance"]
    if not normalized:
        return {"scope": default_scope, "plan_date": None, "focus": ""}

    try:
        parsed = _ollama_json(_analysis_scope_prompt(), normalized)
    except Exception:
        parsed = {}

    raw_scope = parsed.get("scope")
    scope: list[str] = []
    if isinstance(raw_scope, list):
        for item in raw_scope:
            value = str(item or "").strip().lower()
            if value in {"notes", "homework", "grades", "performance"} and value not in scope:
                scope.append(value)

    low = normalized.lower()
    if not scope:
        if any(marker in low for marker in ("заметк", "напомин")):
            scope.append("notes")
        if any(marker in low for marker in ("дз", "домаш", "урок")):
            scope.append("homework")
        if any(marker in low for marker in ("оцен", "балл", "успева")):
            scope.append("grades")
        if any(marker in low for marker in ("расплан", "день", "нагруз", "расписан")):
            for item in ("performance", "homework", "notes"):
                if item not in scope:
                    scope.append(item)

    if not scope:
        scope = default_scope

    plan_date = parsed.get("plan_date")
    if plan_date in ("", "null", None):
        plan_date = None
    else:
        plan_date = str(plan_date).strip() or None

    if not plan_date:
        low = normalized.lower()
        if "завтра" in low:
            plan_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        elif "сегодня" in low:
            plan_date = datetime.now().strftime("%Y-%m-%d")

    focus = str(parsed.get("focus") or normalized).strip() or normalized
    return {"scope": scope, "plan_date": plan_date, "focus": focus}



NOTE_SUBTASKS_PROMPT = """?? ?????????? ???? ??????? ??? ???? ?? ???????? ?????????. ????????? ?????? ???????? JSON.

???????:
- ???? subtasks ?????? ???? ???????? ?????
- ?????? ?????? ? ???????? ?????????? ???
- ????? ?? 3 ?? 7 ?????, ???? ?????? ??? ?????????
- ?? ???????? ?????? ??????????
- ???? ?????? ??? ????? ???????, ????? ??????? 1-3 ????
- ???? ??-??????

???????:
????: "?????? ????"
?????: {"subtasks": ["?????????, ???? ?? ????, ??????, ???? ? ????", "???????? ????? ? ???????? ??? ?????????", "???????????? ???? ? ????????? ???????", "???????? ?? ??????????", "???????? ???? ????? ????????"]}

????: "????????????? ? ??????????? ?? ???????"
?????: {"subtasks": ["?????????? ????, ??????? ????? ?? ???????????", "????????? ??????? ? ???????", "?????? ????????? ??????? ?????", "????????? ?????? ? ??????? ????????", "??????????? ??? ?????? ? ?????"]}

??????? ??????: {"subtasks": ["??? 1", "??? 2"]}"""


def generate_note_subtasks(note_text: str) -> list[str]:
    normalized = str(note_text or '').strip()
    if not normalized:
        return []

    try:
        parsed = _ollama_json(NOTE_SUBTASKS_PROMPT, normalized)
        raw_items = parsed.get('subtasks')
        if isinstance(raw_items, list):
            cleaned = []
            for item in raw_items:
                value = str(item or '').strip(' -\n\t')
                if value and value not in cleaned:
                    cleaned.append(value)
            if cleaned:
                return cleaned[:7]
    except Exception:
        pass

    parts = [
        part.strip(' -\n\t')
        for part in re.split(r'[,.]|\s+?\s+', normalized)
        if part.strip(' -\n\t')
    ]
    if len(parts) >= 2:
        return parts[:5]

    return [
        f'????????????? ? ??????: {normalized}',
        f'??????? ???????? ???: {normalized}',
        f'????????? ????????? ?? ??????: {normalized}',
    ]

def generate_analysis_reply(user_input: str, context: dict[str, Any]) -> str:
    payload = {
        "request": user_input,
        "context": context,
    }
    messages = [
        {"role": "system", "content": ANALYSIS_REPLY_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
    ]
    return _ollama_chat_free(messages)


# ─────────────────────────────────────────
# ДИАЛОГ (чат)
# ─────────────────────────────────────────
def chat_reply(messages: list[dict[str, str]]) -> str:
    prepared = [{"role": "system", "content": CHAT_SYSTEM_PROMPT}, *messages]
    return _ollama_chat_free(prepared)


# Re-declare homework parsers with clean Russian prompts/markers.
def _teacher_homework_prompt() -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    return f"""Ты извлекаешь домашнее задание из сообщения учителя. Возвращай только JSON.

Поля ответа:
- is_homework: true если это домашнее задание для класса, иначе false
- class_name: класс строго в виде "10 А", "10 Б", "11 А"
- subject: предмет или null
- task: только само задание, без служебных слов
- date: дата строго в формате YYYY-MM-DD или null
- points_value: ценность задания, если не указана -> 1

Сегодня: {today}
Завтра: {tomorrow}

Правила:
- Если есть класс, дата и формулировка задания, считай это домашним заданием
- Нормализуй класс: "10А", "10 а", "10-А" -> "10 А"
- Если есть "завтра", подставляй {tomorrow}
- Если есть "сегодня", подставляй {today}
- Если предмет написан без слова "по", все равно извлекай его
- Не включай в task слова "создай", "дз", "задание", "для 10 А", "на завтра", "по геометрии"
- Короткие форматы тоже являются ДЗ:
  "10А геометрия на завтра №304-307"
  "10 Б физика задачи 227-232 на завтра"
  "11А литература перечитать главу к 2026-04-26"
- Если это не задание для класса, верни is_homework=false

Примеры:
Вход: "10А геометрия на завтра №304-307"
Ответ: {{"is_homework": true, "class_name": "10 А", "subject": "геометрия", "task": "№304-307", "date": "{tomorrow}", "points_value": 1}}

Вход: "создай дз для 10 А на завтра по алгебре: решить №12-15, ценность 3"
Ответ: {{"is_homework": true, "class_name": "10 А", "subject": "алгебра", "task": "решить №12-15", "date": "{tomorrow}", "points_value": 3}}

Вход: "для 11А литература перечитать главу к 2026-04-26"
Ответ: {{"is_homework": true, "class_name": "11 А", "subject": "литература", "task": "перечитать главу", "date": "2026-04-26", "points_value": 1}}

Вход: "объясни закон Ома"
Ответ: {{"is_homework": false, "class_name": null, "subject": null, "task": null, "date": null, "points_value": 1}}

Отвечай строго так:
{{"is_homework": true, "class_name": "<класс>", "subject": "<предмет или null>", "task": "<задание>", "date": "<YYYY-MM-DD или null>", "points_value": 1}}"""


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
        "урок",
        "добавь дз",
    )
    has_marker = any(marker in raw for marker in homework_markers)
    has_class = bool(re.search(r"\b\d{1,2}\s*[- ]?\s*[а-яёa-z]\b", raw))
    has_due_date = (
        bool(re.search(r"\d{4}-\d{2}-\d{2}", raw))
        or "завтра" in raw
        or "сегодня" in raw
        or bool(re.search(r"\d{1,2}\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)", raw))
    )
    has_subject = bool(re.search(r"\b(алгебра|геометрия|математика|физика|химия|биология|история|литература|информатика|английский\s+язык|обж|география)\b", raw))
    has_task_shape = bool(re.search(r"(№\s*\d+|упр\.?\s*\d+|задач|параграф|стр\.?\s*\d+|решить|прочитать|перечитать|выучить|подготовить)", raw))

    return has_marker or (has_class and (has_due_date or has_subject) and has_task_shape)


def _extract_subject(raw: str) -> str | None:
    low = str(raw or "").lower()
    match = re.search(r"\bпо\s+([а-яё\- ]+?)(?=[:;,]|\s+на\b|\s+к\b|\s\d{4}-\d{2}-\d{2}|$)", low)
    if match:
        return match.group(1).strip(" .,:;")

    class_match = re.search(r"\b\d{1,2}\s*[- ]?\s*[а-яёa-z]\b\s+([а-яё\- ]+?)(?=\s+на\b|\s+к\b|\s\d{4}-\d{2}-\d{2}\b|:|,|;|$)", low)
    if class_match:
        candidate = class_match.group(1).strip(" .,:;")
        if candidate and len(candidate.split()) <= 3:
            return candidate
    return None


def _extract_homework_task(raw: str, class_name: str | None, subject: str | None, date_value: str | None) -> str | None:
    text = str(raw or "").strip()
    if not text:
        return None

    if ":" in text:
        after_colon = text.split(":", 1)[1].strip()
        if after_colon:
            return after_colon

    cleaned = text
    for pattern in (
        r"(?i)\bсоздай\b",
        r"(?i)\bсоздать\b",
        r"(?i)\bзадай\b",
        r"(?i)\bдобавь\b",
        r"(?i)\bдомашнее задание\b",
        r"(?i)\bдз\b",
        r"(?i)\bдля\b",
        r"(?i)\bк\b",
        r"(?i)\bна\b",
    ):
        cleaned = re.sub(pattern, "", cleaned)

    if class_name:
        cleaned = re.sub(re.escape(class_name), "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(re.escape(class_name.replace(" ", "")), "", cleaned, flags=re.IGNORECASE)
    if subject:
        cleaned = re.sub(rf"(?i)\bпо\s+{re.escape(subject)}\b", "", cleaned)
        cleaned = re.sub(rf"(?i)\b{re.escape(subject)}\b", "", cleaned)

    cleaned = re.sub(r"\d{4}-\d{2}-\d{2}", "", cleaned)
    cleaned = re.sub(r"(?i)\b(сегодня|завтра)\b", "", cleaned)
    cleaned = re.sub(r"(?i)\b\d{1,2}\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)(\s+\d{4})?\b", "", cleaned)
    cleaned = re.sub(r"(?i)\b(алгебра|геометрия|математика|физика|химия|биология|история|литература|информатика|английский\s+язык|обж|география)\b", "", cleaned)
    cleaned = re.sub(r"(?i)\b(ценность|стоимость)\s*\d+\b", "", cleaned)
    cleaned = re.sub(r"(?i)\b\d+\s*очк[а-я]*\b", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,:;")
    return cleaned or None


def _parse_teacher_homework_without_llm(user_input: str) -> dict[str, Any]:
    normalized = str(user_input or "").strip()
    class_name = _normalize_class_name(normalized)
    date_value = _extract_due_date(normalized)
    subject = _extract_subject(normalized)
    task = _extract_homework_task(normalized, class_name, subject, date_value)
    points_value = _extract_points_value(normalized)
    has_homework_intent = _looks_like_teacher_homework(normalized)
    is_homework = bool(class_name and task and (date_value or has_homework_intent) and has_homework_intent)
    return {
        "is_homework": is_homework,
        "class_name": class_name,
        "subject": subject,
        "task": task,
        "date": date_value,
        "points_value": points_value,
    }


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
                "points_value": data.get("points_value", 1),
            }

        if category == 4:
            data = extract_analysis_scope(normalized)
            return {
                "category": 4,
                "scope": data.get("scope", []),
                "plan_date": data.get("plan_date"),
                "focus": data.get("focus", normalized),
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
