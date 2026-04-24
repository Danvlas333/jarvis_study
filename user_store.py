import json
import os
import secrets
from datetime import date, datetime, timedelta, timezone
from typing import Any


DEFAULT_STUDENT_POINTS = 0
DEFAULT_HOMEWORK_POINTS = 1
WEEKLY_GOAL_REWARD_POINTS = 5


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_student_points() -> dict[str, Any]:
    return {
        "score": DEFAULT_STUDENT_POINTS,
        "updated_at": _utc_now(),
        "last_delta": 0,
        "last_reason": "",
    }


def build_points_profile(points_payload: dict[str, Any] | None) -> dict[str, Any]:
    score_raw = (points_payload or {}).get("score", DEFAULT_STUDENT_POINTS) if isinstance(points_payload, dict) else DEFAULT_STUDENT_POINTS
    try:
        score = max(0, int(score_raw))
    except (TypeError, ValueError):
        score = DEFAULT_STUDENT_POINTS

    ranks = [
        {"min": 0, "title": "Новичок класса"},
        {"min": 5, "title": "Старательный ученик"},
        {"min": 12, "title": "Отличник практики"},
        {"min": 20, "title": "Хранитель дневника"},
        {"min": 35, "title": "Староста знаний"},
        {"min": 50, "title": "Магистр предметов"},
        {"min": 75, "title": "Академический наставник"},
    ]

    current_rank = ranks[0]
    next_rank: dict[str, Any] | None = None
    for index, rank in enumerate(ranks):
        if score >= int(rank["min"]):
            current_rank = rank
            next_rank = ranks[index + 1] if index + 1 < len(ranks) else None
        else:
            break

    points_to_next = max(0, int(next_rank["min"]) - score) if next_rank else 0
    progress_base = int(current_rank["min"])
    progress_target = int(next_rank["min"]) if next_rank else score or 1
    progress_span = max(1, progress_target - progress_base)
    progress_value = min(progress_span, max(0, score - progress_base))
    progress_percent = 100 if next_rank is None else round((progress_value / progress_span) * 100)

    return {
        "score": score,
        "title": str(current_rank["title"]),
        "next_title": str(next_rank["title"]) if next_rank else "",
        "next_threshold": int(next_rank["min"]) if next_rank else score,
        "points_to_next": points_to_next,
        "progress_percent": progress_percent,
    }


def _default_student_streak() -> dict[str, Any]:
    return {
        "current": 0,
        "best": 0,
        "last_completed_on": "",
        "updated_at": _utc_now(),
    }


def _default_weekly_goal() -> dict[str, Any]:
    return {
        "week_key": "",
        "task": "",
        "subject": "",
        "points_reward": WEEKLY_GOAL_REWARD_POINTS,
        "note_id": "",
        "created_at": "",
    }


def _parse_homework_due_date(raw_value: Any) -> date | None:
    normalized = str(raw_value or "").strip()
    if not normalized:
        return None
    try:
        return datetime.fromisoformat(normalized).date()
    except ValueError:
        return None


def _normalize_homework_gamification_fields(item: dict[str, Any]) -> bool:
    changed = False
    for key in ("rating_reward_applied", "rating_penalty_applied"):
        if not isinstance(item.get(key), bool):
            item[key] = bool(item.get(key, False))
            changed = True
    return changed


def _normalize_homework_points_value(item: dict[str, Any]) -> bool:
    changed = False
    try:
        points_value = int(item.get("points_value", DEFAULT_HOMEWORK_POINTS))
    except (TypeError, ValueError):
        points_value = DEFAULT_HOMEWORK_POINTS
    points_value = max(1, points_value)
    if item.get("points_value") != points_value:
        item["points_value"] = points_value
        changed = True
    return changed


def _normalize_student_points(payload: dict[str, Any]) -> bool:
    current = payload.get("points")
    if not isinstance(current, dict):
        payload["points"] = _default_student_points()
        return True

    changed = False
    try:
        score = int(current.get("score", DEFAULT_STUDENT_POINTS))
    except (TypeError, ValueError):
        score = DEFAULT_STUDENT_POINTS
    score = max(0, score)
    if current.get("score") != score:
        current["score"] = score
        changed = True

    updated_at = str(current.get("updated_at") or "").strip()
    if not updated_at:
        current["updated_at"] = _utc_now()
        changed = True

    try:
        last_delta = int(current.get("last_delta", 0))
    except (TypeError, ValueError):
        last_delta = 0
    if current.get("last_delta") != last_delta:
        current["last_delta"] = last_delta
        changed = True

    last_reason = str(current.get("last_reason") or "")
    if current.get("last_reason") != last_reason:
        current["last_reason"] = last_reason
        changed = True

    return changed


def _normalize_student_streak(payload: dict[str, Any]) -> bool:
    current = payload.get("streak")
    if not isinstance(current, dict):
        payload["streak"] = _default_student_streak()
        return True

    changed = False
    for key in ("current", "best"):
        try:
            value = int(current.get(key, 0))
        except (TypeError, ValueError):
            value = 0
        value = max(0, value)
        if current.get(key) != value:
            current[key] = value
            changed = True

    last_completed_on = str(current.get("last_completed_on") or "").strip()
    if current.get("last_completed_on") != last_completed_on:
        current["last_completed_on"] = last_completed_on
        changed = True

    updated_at = str(current.get("updated_at") or "").strip()
    if not updated_at:
        current["updated_at"] = _utc_now()
        changed = True

    return changed


def _normalize_weekly_goal(payload: dict[str, Any]) -> bool:
    current = payload.get("weekly_goal")
    if not isinstance(current, dict):
        payload["weekly_goal"] = _default_weekly_goal()
        return True

    changed = False
    normalized = _default_weekly_goal()
    normalized.update({
        "week_key": str(current.get("week_key") or "").strip(),
        "task": str(current.get("task") or "").strip(),
        "subject": str(current.get("subject") or "").strip(),
        "note_id": str(current.get("note_id") or "").strip(),
        "created_at": str(current.get("created_at") or "").strip(),
    })
    try:
        normalized["points_reward"] = max(1, int(current.get("points_reward", WEEKLY_GOAL_REWARD_POINTS)))
    except (TypeError, ValueError):
        normalized["points_reward"] = WEEKLY_GOAL_REWARD_POINTS

    if current != normalized:
        payload["weekly_goal"] = normalized
        changed = True
    return changed


def _apply_student_points_delta(payload: dict[str, Any], delta: int, reason: str) -> bool:
    if delta == 0:
        return False
    _normalize_student_points(payload)
    points = payload["points"]
    current_score = int(points.get("score", DEFAULT_STUDENT_POINTS))
    next_score = max(0, current_score + delta)
    points["score"] = next_score
    points["updated_at"] = _utc_now()
    points["last_delta"] = delta
    points["last_reason"] = reason
    return True


def _apply_streak_completion(payload: dict[str, Any], completed_on: str) -> bool:
    _normalize_student_streak(payload)
    streak = payload["streak"]
    completed_date = _parse_homework_due_date(completed_on)
    if completed_date is None:
        return False

    last_date = _parse_homework_due_date(streak.get("last_completed_on"))
    if last_date == completed_date:
        return False
    if last_date and completed_date == last_date + timedelta(days=1):
        current = int(streak.get("current", 0)) + 1
    else:
        current = 1

    streak["current"] = current
    streak["best"] = max(int(streak.get("best", 0)), current)
    streak["last_completed_on"] = completed_date.isoformat()
    streak["updated_at"] = _utc_now()
    return True


def _user_root(data_root: str, storage_key: str) -> str:
    return os.path.join(data_root, storage_key)


def _state_path(data_root: str, storage_key: str) -> str:
    return os.path.join(_user_root(data_root, storage_key), "state.json")


def _chat_dir(data_root: str, storage_key: str) -> str:
    return os.path.join(_user_root(data_root, storage_key), "chats")


def _homework_submission_dir(data_root: str, storage_key: str) -> str:
    return os.path.join(_user_root(data_root, storage_key), "homework_submissions")


def _sanitize_submission_filename(file_name: str) -> str:
    cleaned = os.path.basename(str(file_name or "").strip())
    cleaned = "".join(char for char in cleaned if char not in '<>:"/\\|?*').strip().strip(".")
    return cleaned or "solution.bin"


def save_homework_submission_file(
    data_root: str,
    storage_key: str,
    file_name: str,
    file_bytes: bytes,
    previous_token: str | None = None,
) -> tuple[str, str]:
    submission_dir = _homework_submission_dir(data_root, storage_key)
    os.makedirs(submission_dir, exist_ok=True)

    safe_name = _sanitize_submission_filename(file_name)
    _, extension = os.path.splitext(safe_name)
    token = f"{secrets.token_hex(12)}{extension.lower()}"
    target_path = os.path.join(submission_dir, token)

    with open(target_path, "wb") as file:
        file.write(file_bytes)

    old_token = str(previous_token or "").strip()
    if old_token and old_token != token:
        old_path = os.path.join(submission_dir, os.path.basename(old_token))
        try:
            if os.path.isfile(old_path):
                os.remove(old_path)
        except OSError:
            pass

    return safe_name, token


def get_homework_submission_path(data_root: str, storage_key: str, submission_token: str | None) -> str | None:
    token = os.path.basename(str(submission_token or "").strip())
    if not token:
        return None
    target_path = os.path.join(_homework_submission_dir(data_root, storage_key), token)
    return target_path if os.path.isfile(target_path) else None


def _chat_path(data_root: str, storage_key: str, chat_id: str) -> str:
    return os.path.join(_chat_dir(data_root, storage_key), f"{chat_id}.json")


def _completed_tasks_path(data_root: str, storage_key: str) -> str:
    return os.path.join(_user_root(data_root, storage_key), "completed_tasks.json")


def _student_performance_path(data_root: str, storage_key: str) -> str:
    return os.path.join(_user_root(data_root, storage_key), "student_performance.json")


def _student_grades_path(data_root: str, storage_key: str) -> str:
    return os.path.join(_user_root(data_root, storage_key), "student_grades.json")


def _seed_missed_homework() -> dict[str, Any]:
    return {
        "id": "seed-missed-homework-2026-04-20",
        "kind": "homework",
        "status": "missed",
        "title": "Литература",
        "description": "Прочитать рассказ Чехова и подготовить краткий пересказ.",
        "date": "2026-04-20",
        "archived_at": _utc_now(),
    }


def _seed_example_homework() -> dict[str, Any]:
    return {
        "id": "seed-homework-overdue-2026-04-21",
        "subject": "Алгебра",
        "task": "Решить №531-536 и повторить формулы сокращенного умножения.",
        "date": "2026-04-21",
        "done": False,
        "volume": "medium",
        "priority": "high",
    }


def _default_archive() -> dict[str, list[dict[str, Any]]]:
    return {
        "completed": [],
        "missed": [_seed_missed_homework()],
        "trash": [],
    }


def _seed_shared_homework_items() -> list[dict[str, Any]]:
    return [
        {
            "id": "seed-homework-teacher-10a-algebra-2026-04-20",
            "class_name": "10 Б",
            "subject": "Алгебра",
            "task": "учебник стр. 227-232 учить определения, №168",
            "date": "2026-04-20",
            "done": False,
            "volume": "medium",
            "priority": "high",
            "teacher_reviewed": True,
            "teacher_progress_percent": 100,
            "teacher_checked_count": 28,
            "teacher_total_count": 28,
            "teacher_action_label": "Проверить загруженные решения",
        },
        {
            "id": "seed-homework-teacher-10a-geometry-2026-04-24",
            "class_name": "10 А",
            "subject": "Геометрия",
            "task": "учебник стр 156-189, повт теорию. стр 175 №304-307",
            "date": "2026-04-24",
            "done": False,
            "volume": "medium",
            "priority": "medium",
            "teacher_reviewed": False,
            "teacher_progress_percent": 50,
            "teacher_checked_count": 14,
            "teacher_total_count": 28,
            "teacher_action_label": "Проверить загруженные решения",
        },
    ]

def _default_performance() -> dict[str, list[dict[str, Any]]]:
    return {
        "days": [
            {
                "date": "2026-04-20",
                "title": "Понедельник, 20 апреля",
                "lessons": [
                    {
                        "number": 1,
                        "subject": "алгебра",
                        "time": "8:00 - 8:40",
                        "task": "Учебник стр. 227-232 учить определения, №168-170",
                        "status": "done",
                        "tone": "sky",
                    },
                    {
                        "number": 2,
                        "subject": "алгебра",
                        "time": "8:50 - 9:30",
                        "task": "",
                        "status": "none",
                        "tone": "sky",
                    },
                    {
                        "number": 3,
                        "subject": "геометрия",
                        "time": "9:45 - 10:25",
                        "task": "",
                        "status": "none",
                        "tone": "sky",
                    },
                    {
                        "number": 4,
                        "subject": "физкультура",
                        "time": "10:45 - 11:25",
                        "task": "",
                        "status": "none",
                        "tone": "sky",
                    },
                    {
                        "number": 5,
                        "subject": "литература",
                        "time": "11:45 - 12:25",
                        "task": "Учить \"Войну и мир\" наизусть",
                        "status": "done",
                        "tone": "sky",
                    },
                ],
            },
            {
                "date": "2026-04-21",
                "title": "Вторник, 21 апреля",
                "lessons": [
                    {
                        "number": 1,
                        "subject": "физика",
                        "time": "8:00 - 8:40",
                        "task": "",
                        "status": "none",
                        "tone": "indigo",
                    },
                    {
                        "number": 2,
                        "subject": "физика",
                        "time": "8:50 - 9:30",
                        "task": "Физика: №12-15, 15-17 урока 148. Повторить МКТ",
                        "status": "pending",
                        "tone": "indigo",
                    },
                ],
            },
        ],
    }


def default_teacher_performance() -> dict[str, Any]:
    return {
        "days": [
            {
                "date": "2026-04-20",
                "title": "Понедельник, 20 апреля",
                "lessons": [
                    {
                        "number": 1,
                        "subject": "алгебра",
                        "class_name": "10 А",
                        "time": "8:00 - 8:40",
                        "task": "Учебник стр. 227-232 учить определения, №168-170",
                        "status": "done",
                        "tone": "sky",
                    },
                    {
                        "number": 2,
                        "subject": "алгебра",
                        "class_name": "10 А",
                        "time": "8:50 - 9:30",
                        "task": "",
                        "status": "none",
                        "tone": "sky",
                    },
                    {
                        "number": 3,
                        "subject": "геометрия",
                        "class_name": "10 Б",
                        "time": "9:45 - 10:25",
                        "task": "",
                        "status": "none",
                        "tone": "sky",
                    },
                    {
                        "number": 4,
                        "subject": "геометрия",
                        "class_name": "10 Б",
                        "time": "10:45 - 11:25",
                        "task": "",
                        "status": "none",
                        "tone": "sky",
                    },
                    {
                        "number": 5,
                        "subject": "вероятность и статистика",
                        "class_name": "11 А",
                        "time": "11:45 - 12:25",
                        "task": "",
                        "status": "none",
                        "tone": "sky",
                    },
                ],
            },
            {
                "date": "2026-04-21",
                "title": "Вторник, 21 апреля",
                "lessons": [
                    {
                        "number": 1,
                        "subject": "геометрия",
                        "class_name": "10 Б",
                        "time": "8:00 - 8:40",
                        "task": "",
                        "status": "none",
                        "tone": "indigo",
                    },
                    {
                        "number": 2,
                        "subject": "геометрия",
                        "class_name": "10 Б",
                        "time": "8:50 - 9:30",
                        "task": "Учебник стр 227 №278-290",
                        "status": "progress",
                        "tone": "indigo",
                        "completion_percent": 75,
                        "completed_count": 21,
                        "total_count": 28,
                    },
                ],
            },
        ],
    }




def _default_student_grades() -> dict[str, Any]:
    payload = json.loads(r'''{
  "title": "\u041c\u043e\u044f \u0443\u0441\u043f\u0435\u0432\u0430\u0435\u043c\u043e\u0441\u0442\u044c",
  "assistant_prompt": "\u0427\u0442\u043e \u0434\u0435\u043b\u0430\u0442\u044c, \u0435\u0441\u043b\u0438 \u0443 \u043c\u0435\u043d\u044f \u043f\u0440\u043e\u0431\u043b\u0435\u043c\u044b \u0441 \u0430\u043d\u0433\u043b\u0438\u0439\u0441\u043a\u0438\u043c?",
  "rating": {
    "score": 100,
    "updated_at": "",
    "last_delta": 0,
    "last_reason": ""
  },
  "current_quarter": "q4",
  "quarters": [
    {
      "id": "q1",
      "label": "1 \u0447\u0435\u0442\u0432\u0435\u0440\u0442\u044c",
      "columns": [
        "2.09",
        "5.09",
        "9.09",
        "12.09",
        "16.09",
        "19.09",
        "23.09",
        "26.09",
        "30.09",
        "3.10",
        "7.10",
        "10.10"
      ],
      "subjects": [
        {
          "name": "\u0410\u043b\u0433\u0435\u0431\u0440\u0430",
          "grades": [
            "4",
            "",
            "5",
            "",
            "",
            "4",
            "",
            "5",
            "",
            "",
            "4",
            ""
          ],
          "average": "4",
          "tone": "good"
        },
        {
          "name": "\u0410\u043d\u0433\u043b\u0438\u0439\u0441\u043a\u0438\u0439 \u044f\u0437\u044b\u043a",
          "grades": [
            "",
            "3",
            "",
            "",
            "4",
            "",
            "",
            "",
            "3",
            "",
            "",
            "4"
          ],
          "average": "4",
          "tone": "good"
        },
        {
          "name": "\u0411\u0438\u043e\u043b\u043e\u0433\u0438\u044f",
          "grades": [
            "",
            "",
            "",
            "5",
            "",
            "",
            "",
            "",
            "",
            "",
            "4",
            ""
          ],
          "average": "5",
          "tone": "good"
        },
        {
          "name": "\u0412\u0435\u0440\u043e\u044f\u0442\u043d\u043e\u0441\u0442\u044c \u0438 \u0441\u0442\u0430\u0442\u0438\u0441\u0442\u0438\u043a\u0430",
          "grades": [
            "",
            "",
            "4",
            "",
            "",
            "",
            "5",
            "",
            "",
            "",
            "",
            ""
          ],
          "average": "5",
          "tone": "good"
        },
        {
          "name": "\u0413\u0435\u043e\u0433\u0440\u0430\u0444\u0438\u044f",
          "grades": [
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            ""
          ],
          "average": "",
          "tone": "none"
        },
        {
          "name": "\u0418\u0441\u0442\u043e\u0440\u0438\u044f",
          "grades": [
            "5",
            "",
            "",
            "",
            "4",
            "",
            "",
            "5",
            "",
            "",
            "",
            ""
          ],
          "average": "5",
          "tone": "good"
        },
        {
          "name": "\u0425\u0438\u043c\u0438\u044f",
          "grades": [
            "",
            "",
            "4",
            "",
            "",
            "5",
            "",
            "",
            "",
            "4",
            "",
            ""
          ],
          "average": "4",
          "tone": "good"
        },
        {
          "name": "\u0424\u0438\u0437\u0438\u043a\u0430",
          "grades": [
            "",
            "4",
            "",
            "",
            "",
            "",
            "4",
            "",
            "",
            "",
            "5",
            ""
          ],
          "average": "4",
          "tone": "good"
        },
        {
          "name": "\u0418\u043d\u0444\u043e\u0440\u043c\u0430\u0442\u0438\u043a\u0430",
          "grades": [
            "5",
            "",
            "",
            "5",
            "",
            "",
            "",
            "",
            "5",
            "",
            "",
            ""
          ],
          "average": "5",
          "tone": "good"
        }
      ],
      "completion_percent": 93,
      "risk_subjects": [
        {
          "key": "\u0430\u043b\u0433",
          "value": 4,
          "tone": "good"
        },
        {
          "key": "\u0430\u043d\u0433\u043b",
          "value": 3,
          "tone": "bad"
        },
        {
          "key": "\u0431\u0438\u043e",
          "value": 5,
          "tone": "good"
        },
        {
          "key": "\u0432\u0438\u0441",
          "value": 5,
          "tone": "good"
        },
        {
          "key": "\u0433\u0435\u043e\u0433",
          "value": 0,
          "tone": "none"
        }
      ]
    },
    {
      "id": "q2",
      "label": "2 \u0447\u0435\u0442\u0432\u0435\u0440\u0442\u044c",
      "columns": [
        "5.11",
        "8.11",
        "12.11",
        "15.11",
        "19.11",
        "22.11",
        "26.11",
        "29.11",
        "3.12",
        "6.12",
        "10.12",
        "13.12"
      ],
      "subjects": [
        {
          "name": "\u0410\u043b\u0433\u0435\u0431\u0440\u0430",
          "grades": [
            "5",
            "",
            "",
            "4",
            "",
            "",
            "5",
            "",
            "",
            "5",
            "",
            ""
          ],
          "average": "5",
          "tone": "good"
        },
        {
          "name": "\u0410\u043d\u0433\u043b\u0438\u0439\u0441\u043a\u0438\u0439 \u044f\u0437\u044b\u043a",
          "grades": [
            "",
            "2",
            "",
            "",
            "",
            "3",
            "",
            "",
            "",
            "",
            "3",
            ""
          ],
          "average": "3",
          "tone": "bad"
        },
        {
          "name": "\u0411\u0438\u043e\u043b\u043e\u0433\u0438\u044f",
          "grades": [
            "",
            "",
            "",
            "",
            "4",
            "",
            "",
            "",
            "5",
            "",
            "",
            ""
          ],
          "average": "5",
          "tone": "good"
        },
        {
          "name": "\u0412\u0435\u0440\u043e\u044f\u0442\u043d\u043e\u0441\u0442\u044c \u0438 \u0441\u0442\u0430\u0442\u0438\u0441\u0442\u0438\u043a\u0430",
          "grades": [
            "",
            "",
            "5",
            "",
            "",
            "",
            "",
            "5",
            "",
            "",
            "",
            ""
          ],
          "average": "5",
          "tone": "good"
        },
        {
          "name": "\u0413\u0435\u043e\u0433\u0440\u0430\u0444\u0438\u044f",
          "grades": [
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            ""
          ],
          "average": "",
          "tone": "none"
        },
        {
          "name": "\u0418\u0441\u0442\u043e\u0440\u0438\u044f",
          "grades": [
            "4",
            "",
            "",
            "",
            "",
            "4",
            "",
            "",
            "",
            "5",
            "",
            ""
          ],
          "average": "4",
          "tone": "good"
        },
        {
          "name": "\u0425\u0438\u043c\u0438\u044f",
          "grades": [
            "",
            "",
            "3",
            "",
            "",
            "",
            "4",
            "",
            "",
            "",
            "4",
            ""
          ],
          "average": "4",
          "tone": "good"
        },
        {
          "name": "\u0424\u0438\u0437\u0438\u043a\u0430",
          "grades": [
            "",
            "4",
            "",
            "",
            "5",
            "",
            "",
            "",
            "",
            "",
            "",
            "5"
          ],
          "average": "5",
          "tone": "good"
        },
        {
          "name": "\u0418\u043d\u0444\u043e\u0440\u043c\u0430\u0442\u0438\u043a\u0430",
          "grades": [
            "5",
            "",
            "",
            "5",
            "",
            "",
            "",
            "",
            "5",
            "",
            "",
            "5"
          ],
          "average": "5",
          "tone": "good"
        }
      ],
      "completion_percent": 90,
      "risk_subjects": [
        {
          "key": "\u0430\u043b\u0433",
          "value": 5,
          "tone": "good"
        },
        {
          "key": "\u0430\u043d\u0433\u043b",
          "value": 2,
          "tone": "bad"
        },
        {
          "key": "\u0431\u0438\u043e",
          "value": 4,
          "tone": "good"
        },
        {
          "key": "\u0432\u0438\u0441",
          "value": 5,
          "tone": "good"
        },
        {
          "key": "\u0433\u0435\u043e\u0433",
          "value": 0,
          "tone": "none"
        }
      ]
    },
    {
      "id": "q3",
      "label": "3 \u0447\u0435\u0442\u0432\u0435\u0440\u0442\u044c",
      "columns": [
        "13.01",
        "16.01",
        "20.01",
        "23.01",
        "27.01",
        "30.01",
        "3.02",
        "6.02",
        "10.02",
        "13.02",
        "17.02",
        "20.02"
      ],
      "subjects": [
        {
          "name": "\u0410\u043b\u0433\u0435\u0431\u0440\u0430",
          "grades": [
            "4",
            "",
            "4",
            "",
            "",
            "5",
            "",
            "",
            "5",
            "",
            "",
            "4"
          ],
          "average": "4",
          "tone": "good"
        },
        {
          "name": "\u0410\u043d\u0433\u043b\u0438\u0439\u0441\u043a\u0438\u0439 \u044f\u0437\u044b\u043a",
          "grades": [
            "",
            "3",
            "",
            "",
            "3",
            "",
            "",
            "",
            "",
            "4",
            "",
            ""
          ],
          "average": "3",
          "tone": "bad"
        },
        {
          "name": "\u0411\u0438\u043e\u043b\u043e\u0433\u0438\u044f",
          "grades": [
            "",
            "",
            "",
            "4",
            "",
            "",
            "",
            "",
            "",
            "",
            "4",
            ""
          ],
          "average": "4",
          "tone": "good"
        },
        {
          "name": "\u0412\u0435\u0440\u043e\u044f\u0442\u043d\u043e\u0441\u0442\u044c \u0438 \u0441\u0442\u0430\u0442\u0438\u0441\u0442\u0438\u043a\u0430",
          "grades": [
            "",
            "",
            "5",
            "",
            "",
            "",
            "5",
            "",
            "",
            "",
            "",
            ""
          ],
          "average": "5",
          "tone": "good"
        },
        {
          "name": "\u0413\u0435\u043e\u0433\u0440\u0430\u0444\u0438\u044f",
          "grades": [
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            ""
          ],
          "average": "",
          "tone": "none"
        },
        {
          "name": "\u0418\u0441\u0442\u043e\u0440\u0438\u044f",
          "grades": [
            "4",
            "",
            "",
            "",
            "4",
            "",
            "",
            "5",
            "",
            "",
            "",
            ""
          ],
          "average": "4",
          "tone": "good"
        },
        {
          "name": "\u0425\u0438\u043c\u0438\u044f",
          "grades": [
            "",
            "",
            "4",
            "",
            "",
            "4",
            "",
            "",
            "",
            "5",
            "",
            ""
          ],
          "average": "4",
          "tone": "good"
        },
        {
          "name": "\u0424\u0438\u0437\u0438\u043a\u0430",
          "grades": [
            "",
            "5",
            "",
            "",
            "",
            "",
            "5",
            "",
            "",
            "",
            "",
            "4"
          ],
          "average": "5",
          "tone": "good"
        },
        {
          "name": "\u0418\u043d\u0444\u043e\u0440\u043c\u0430\u0442\u0438\u043a\u0430",
          "grades": [
            "5",
            "",
            "",
            "5",
            "",
            "",
            "",
            "",
            "5",
            "",
            "",
            ""
          ],
          "average": "5",
          "tone": "good"
        }
      ],
      "completion_percent": 91,
      "risk_subjects": [
        {
          "key": "\u0430\u043b\u0433",
          "value": 4,
          "tone": "good"
        },
        {
          "key": "\u0430\u043d\u0433\u043b",
          "value": 3,
          "tone": "bad"
        },
        {
          "key": "\u0431\u0438\u043e",
          "value": 4,
          "tone": "good"
        },
        {
          "key": "\u0432\u0438\u0441",
          "value": 5,
          "tone": "good"
        },
        {
          "key": "\u0433\u0435\u043e\u0433",
          "value": 0,
          "tone": "none"
        }
      ]
    },
    {
      "id": "q4",
      "label": "4 \u0447\u0435\u0442\u0432\u0435\u0440\u0442\u044c",
      "columns": [
        "1.03",
        "4.03",
        "7.03",
        "10.03",
        "13.03",
        "16.03",
        "19.03",
        "22.03",
        "25.03",
        "28.03",
        "31.03",
        "3.04",
        "6.04",
        "9.04",
        "12.04",
        "15.04",
        "18.04",
        "21.04",
        "24.04",
        "27.04",
        "30.04"
      ],
      "subjects": [
        {
          "name": "\u0410\u043b\u0433\u0435\u0431\u0440\u0430",
          "grades": [
            "5",
            "",
            "4",
            "",
            "",
            "5",
            "",
            "",
            "4",
            "",
            "",
            "",
            "",
            "5",
            "",
            "",
            "4",
            "",
            "",
            "",
            ""
          ],
          "average": "5",
          "tone": "good"
        },
        {
          "name": "\u0410\u043d\u0433\u043b\u0438\u0439\u0441\u043a\u0438\u0439 \u044f\u0437\u044b\u043a",
          "grades": [
            "",
            "2",
            "",
            "",
            "3",
            "",
            "",
            "",
            "",
            "",
            "4",
            "",
            "",
            "",
            "",
            "3",
            "",
            "",
            "",
            "",
            "4"
          ],
          "average": "3",
          "tone": "bad"
        },
        {
          "name": "\u0411\u0438\u043e\u043b\u043e\u0433\u0438\u044f",
          "grades": [
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            ""
          ],
          "average": "",
          "tone": "none"
        },
        {
          "name": "\u0412\u0435\u0440\u043e\u044f\u0442\u043d\u043e\u0441\u0442\u044c \u0438 \u0441\u0442\u0430\u0442\u0438\u0441\u0442\u0438\u043a\u0430",
          "grades": [
            "",
            "",
            "",
            "5",
            "",
            "",
            "",
            "5",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "5",
            "",
            "",
            ""
          ],
          "average": "5",
          "tone": "good"
        },
        {
          "name": "\u0413\u0435\u043e\u0433\u0440\u0430\u0444\u0438\u044f",
          "grades": [
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            ""
          ],
          "average": "",
          "tone": "none"
        },
        {
          "name": "\u0418\u0441\u0442\u043e\u0440\u0438\u044f",
          "grades": [
            "4",
            "",
            "",
            "5",
            "",
            "",
            "",
            "",
            "4",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "5",
            "",
            "",
            "",
            ""
          ],
          "average": "4",
          "tone": "good"
        },
        {
          "name": "\u0425\u0438\u043c\u0438\u044f",
          "grades": [
            "",
            "",
            "3",
            "",
            "",
            "4",
            "",
            "",
            "",
            "",
            "",
            "5",
            "",
            "",
            "",
            "",
            "",
            "",
            "4",
            "",
            ""
          ],
          "average": "4",
          "tone": "good"
        },
        {
          "name": "\u0424\u0438\u0437\u0438\u043a\u0430",
          "grades": [
            "",
            "4",
            "",
            "",
            "",
            "",
            "5",
            "",
            "",
            "",
            "",
            "",
            "",
            "4",
            "",
            "",
            "",
            "",
            "",
            "5",
            ""
          ],
          "average": "5",
          "tone": "good"
        },
        {
          "name": "\u0418\u043d\u0444\u043e\u0440\u043c\u0430\u0442\u0438\u043a\u0430",
          "grades": [
            "5",
            "",
            "",
            "",
            "5",
            "",
            "",
            "",
            "",
            "5",
            "",
            "",
            "",
            "",
            "",
            "5",
            "",
            "",
            "",
            "",
            "5"
          ],
          "average": "5",
          "tone": "good"
        }
      ],
      "completion_percent": 88,
      "risk_subjects": [
        {
          "key": "\u0430\u043b\u0433",
          "value": 5,
          "tone": "good"
        },
        {
          "key": "\u0430\u043d\u0433\u043b",
          "value": 2,
          "tone": "bad"
        },
        {
          "key": "\u0431\u0438\u043e",
          "value": 0,
          "tone": "none"
        },
        {
          "key": "\u0432\u0438\u0441",
          "value": 5,
          "tone": "good"
        },
        {
          "key": "\u0433\u0435\u043e\u0433",
          "value": 0,
          "tone": "none"
        }
      ]
    }
  ]
}''')
    payload["points"] = _default_student_points()
    payload["streak"] = _default_student_streak()
    payload["weekly_goal"] = _default_weekly_goal()
    return payload


def _default_state() -> dict[str, Any]:
    return {
        "homework": _seed_shared_homework_items(),
        "notes": [],
        "searches": [],
        "chat_sessions": [],
        "removed_seed_homework_ids": [],
    }


def _merge_seeded_homework_item(seed_item: dict[str, Any], existing_item: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(existing_item, dict):
        merged = dict(seed_item)
        _normalize_homework_gamification_fields(merged)
        _normalize_homework_points_value(merged)
        return merged

    merged = dict(seed_item)
    for key in (
        "done",
        "completed_at",
        "points_value",
        "rating_reward_applied",
        "rating_penalty_applied",
        "rating_penalized_at",
        "submitted_at",
        "submitted_file_name",
        "submitted_file_token",
        "submitted_text",
        "homework_grade",
        "teacher_reviewed",
        "teacher_progress_percent",
        "teacher_checked_count",
        "teacher_total_count",
        "teacher_action_label",
        "created_at",
        "assigned_by",
        "source",
    ):
        if key == "source":
            existing_source = str(existing_item.get("source") or "").strip()
            if existing_source:
                merged[key] = existing_source
            continue
        if key in existing_item:
            merged[key] = existing_item[key]
    _normalize_homework_gamification_fields(merged)
    _normalize_homework_points_value(merged)
    return merged


def _normalize_state(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        state = _default_state()
    else:
        state = {
            "homework": [item for item in payload.get("homework", []) if isinstance(item, dict)],
            "notes": [item for item in payload.get("notes", []) if isinstance(item, dict)],
            "searches": [item for item in payload.get("searches", []) if isinstance(item, dict)],
            "chat_sessions": [item for item in payload.get("chat_sessions", []) if isinstance(item, dict)],
            "removed_seed_homework_ids": [str(item).strip() for item in payload.get("removed_seed_homework_ids", []) if str(item).strip()],
        }

    existing_homework = [
        item for item in state["homework"]
        if str(item.get("id", "")).strip() != "seed-homework-overdue-2026-04-21"
    ]
    seeded_items = _seed_shared_homework_items()
    seeded_ids = {item["id"] for item in seeded_items}
    removed_seed_ids = set(state.get("removed_seed_homework_ids", []))
    existing_seeded_items = {
        str(item.get("id", "")).strip(): item
        for item in existing_homework
        if str(item.get("id", "")).strip() in seeded_ids
    }
    state["homework"] = [
        item for item in existing_homework
        if str(item.get("id", "")).strip() not in seeded_ids
    ]
    for item in state["homework"]:
        if not str(item.get("source") or "").strip() and (
            item.get("teacher_total_count") is not None
            or str(item.get("teacher_action_label") or "").strip()
        ):
            item["source"] = "teacher"
        _normalize_homework_gamification_fields(item)
        _normalize_homework_points_value(item)
    for seeded_item in reversed(seeded_items):
        if seeded_item["id"] in removed_seed_ids:
            continue
        state["homework"].insert(0, _merge_seeded_homework_item(seeded_item, existing_seeded_items.get(seeded_item["id"])))
    for item in state["homework"]:
        if not str(item.get("source") or "").strip() and (
            item.get("teacher_total_count") is not None
            or str(item.get("teacher_action_label") or "").strip()
        ):
            item["source"] = "teacher"
    return state


def ensure_user_storage(data_root: str, storage_key: str) -> None:
    os.makedirs(_chat_dir(data_root, storage_key), exist_ok=True)
    state_path = _state_path(data_root, storage_key)
    if not os.path.exists(state_path):
        with open(state_path, "w", encoding="utf-8") as file:
            json.dump(_default_state(), file, ensure_ascii=False, indent=2)
    completed_tasks_path = _completed_tasks_path(data_root, storage_key)
    if not os.path.exists(completed_tasks_path):
        with open(completed_tasks_path, "w", encoding="utf-8") as file:
            json.dump(_default_archive(), file, ensure_ascii=False, indent=2)
    student_performance_path = _student_performance_path(data_root, storage_key)
    if not os.path.exists(student_performance_path):
        with open(student_performance_path, "w", encoding="utf-8") as file:
            json.dump(_default_performance(), file, ensure_ascii=False, indent=2)
    student_grades_path = _student_grades_path(data_root, storage_key)
    if not os.path.exists(student_grades_path):
        with open(student_grades_path, "w", encoding="utf-8") as file:
            json.dump(_default_student_grades(), file, ensure_ascii=False, indent=2)


def load_state(data_root: str, storage_key: str) -> dict[str, Any]:
    ensure_user_storage(data_root, storage_key)
    with open(_state_path(data_root, storage_key), "r", encoding="utf-8") as file:
        payload = json.load(file)
    normalized = _normalize_state(payload)
    save_state(data_root, storage_key, normalized)
    return normalized


def save_state(data_root: str, storage_key: str, state: dict[str, Any]) -> None:
    ensure_user_storage(data_root, storage_key)
    with open(_state_path(data_root, storage_key), "w", encoding="utf-8") as file:
        json.dump(_normalize_state(state), file, ensure_ascii=False, indent=2)


def _normalize_archive_entry(item: dict[str, Any], status: str) -> dict[str, Any]:
    result = item.get("result", {}) if isinstance(item.get("result"), dict) else {}
    return {
        "id": item.get("id") or secrets.token_hex(8),
        "kind": item.get("kind") or ("homework" if item.get("kind") == "homework" else "note"),
        "status": item.get("status") or status,
        "title": item.get("title") or ("Домашнее задание" if item.get("kind") == "homework" else "Личное задание"),
        "description": item.get("description") or result.get("task") or item.get("source_text") or "Без описания",
        "date": item.get("date") or result.get("date"),
        "archived_at": item.get("archived_at") or item.get("completed_at") or item.get("saved_at") or _utc_now(),
    }


def _normalize_archive_store(payload: Any) -> dict[str, list[dict[str, Any]]]:
    if isinstance(payload, list):
        store = {
            "completed": [_normalize_archive_entry(item, "completed") for item in payload if isinstance(item, dict)],
            "missed": [],
            "trash": [],
        }
    elif isinstance(payload, dict):
        store = {
            "completed": [_normalize_archive_entry(item, "completed") for item in payload.get("completed", []) if isinstance(item, dict)],
            "missed": [_normalize_archive_entry(item, "missed") for item in payload.get("missed", []) if isinstance(item, dict)],
            "trash": [_normalize_archive_entry(item, "trash") for item in payload.get("trash", []) if isinstance(item, dict)],
        }
    else:
        store = _default_archive()

    if not any(item.get("id") == "seed-missed-homework-2026-04-20" for item in store["missed"]):
        store["missed"].append(_seed_missed_homework())
    return store


def load_completed_tasks(data_root: str, storage_key: str) -> dict[str, list[dict[str, Any]]]:
    ensure_user_storage(data_root, storage_key)
    with open(_completed_tasks_path(data_root, storage_key), "r", encoding="utf-8") as file:
        payload = json.load(file)
    normalized = _normalize_archive_store(payload)
    save_completed_tasks(data_root, storage_key, normalized)
    return normalized


def save_completed_tasks(data_root: str, storage_key: str, items: dict[str, list[dict[str, Any]]]) -> None:
    ensure_user_storage(data_root, storage_key)
    with open(_completed_tasks_path(data_root, storage_key), "w", encoding="utf-8") as file:
        json.dump(items, file, ensure_ascii=False, indent=2)


def load_student_performance(data_root: str, storage_key: str) -> dict[str, list[dict[str, Any]]]:
    ensure_user_storage(data_root, storage_key)
    with open(_student_performance_path(data_root, storage_key), "r", encoding="utf-8") as file:
        return json.load(file)


def _parse_student_grades_updated_at(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _subject_grade_values(subject: dict[str, Any]) -> list[float]:
    values: list[float] = []
    for grade in subject.get("grades", []):
        try:
            numeric = float(str(grade).strip().replace(",", "."))
        except (TypeError, ValueError):
            continue
        if numeric > 0:
            values.append(numeric)
    return values


def _subject_average(subject: dict[str, Any]) -> float | None:
    values = _subject_grade_values(subject)
    if values:
        return sum(values) / len(values)
    try:
        numeric = float(str(subject.get("average") or "").strip().replace(",", "."))
    except (TypeError, ValueError):
        return None
    return numeric if numeric > 0 else None


def _refresh_student_grades_insights(payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    last_updated = _parse_student_grades_updated_at(payload.get("assistant_updated_at"))
    now = datetime.now(timezone.utc)
    if last_updated and (now - last_updated).total_seconds() < 24 * 60 * 60:
        return payload, False

    subject_totals: dict[str, list[float]] = {}
    for quarter in payload.get("quarters", []):
        for subject in quarter.get("subjects", []):
            subject_name = str(subject.get("name") or "").strip()
            if not subject_name:
                continue
            values = _subject_grade_values(subject)
            if not values:
                average_value = _subject_average(subject)
                if average_value is not None:
                    values = [average_value]
            if not values:
                continue
            subject_totals.setdefault(subject_name, []).extend(values)

    weakest_subject = ""
    weakest_average: float | None = None
    for subject_name, values in subject_totals.items():
        if not values:
            continue
        average_value = sum(values) / len(values)
        if weakest_average is None or average_value < weakest_average or (
            average_value == weakest_average and subject_name < weakest_subject
        ):
            weakest_subject = subject_name
            weakest_average = average_value

    changed = (
        payload.get("assistant_subject") != weakest_subject
        or payload.get("assistant_updated_at") != now.isoformat()
    )
    payload["assistant_subject"] = weakest_subject
    payload["assistant_updated_at"] = now.isoformat()
    return payload, changed


def _current_week_key(today_value: date | None = None) -> str:
    today_date = today_value or datetime.now(timezone.utc).date()
    iso_year, iso_week, _ = today_date.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def _build_weekly_goal_fallback(payload: dict[str, Any], state: dict[str, Any]) -> tuple[str, str]:
    weakest_subject = str(payload.get("assistant_subject") or "").strip()
    pending_homework = [
        item for item in state.get("homework", [])
        if isinstance(item, dict) and not bool(item.get("done"))
    ]
    if weakest_subject and pending_homework:
        return (
            f"Набрать {WEEKLY_GOAL_REWARD_POINTS} очков: закрой 2 задания по предмету {weakest_subject} и не оставляй просрочку до конца недели.",
            weakest_subject,
        )
    if weakest_subject:
        return (
            f"Набрать {WEEKLY_GOAL_REWARD_POINTS} очков: удели 30 минут повторению по предмету {weakest_subject} и закрой хотя бы одно задание до конца недели.",
            weakest_subject,
        )
    if pending_homework:
        return (
            f"Набрать {WEEKLY_GOAL_REWARD_POINTS} очков: выполни 3 текущих задания без пропусков до конца недели.",
            "",
        )
    return (
        f"Набрать {WEEKLY_GOAL_REWARD_POINTS} очков: поддерживай streak и выполни следующее домашнее задание вовремя.",
        "",
    )


def _build_weekly_goal_with_ai(payload: dict[str, Any], state: dict[str, Any]) -> tuple[str, str]:
    try:
        import ollama  # type: ignore
    except Exception:
        return _build_weekly_goal_fallback(payload, state)

    week_payload = {
        "assistant_subject": payload.get("assistant_subject"),
        "current_quarter": payload.get("current_quarter"),
        "homework": [
            {
                "subject": item.get("subject"),
                "task": item.get("task"),
                "date": item.get("date"),
                "done": item.get("done"),
            }
            for item in state.get("homework", [])[:10]
            if isinstance(item, dict)
        ],
        "notes": [
            (item.get("result") or {}).get("task") or item.get("source_text")
            for item in state.get("notes", [])[:5]
            if isinstance(item, dict)
        ],
    }
    system_prompt = (
        "Ты создаешь одну короткую недельную учебную цель для школьника. "
        "Цель должна быть конкретной, выполнимой за неделю и звучать как задание в заметках. "
        "Учитывай слабый предмет и невыполненные домашние задания. "
        "Верни только JSON вида "
        "{\"task\":\"...\", \"subject\":\"...\"}."
    )
    try:
        response = ollama.chat(
            model=os.getenv("OLLAMA_MODEL", "qwen2.5:3b"),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(week_payload, ensure_ascii=False)},
            ],
            format="json",
            options={"temperature": 0.2},
        )
        raw = (response.get("message") or {}).get("content") or "{}"
        parsed = json.loads(raw)
        task = str(parsed.get("task") or "").strip()
        subject = str(parsed.get("subject") or payload.get("assistant_subject") or "").strip()
        if task:
            return task, subject
    except Exception:
        pass
    return _build_weekly_goal_fallback(payload, state)


def ensure_weekly_goal_note(data_root: str, storage_key: str, grades_payload: dict[str, Any] | None = None) -> tuple[dict[str, Any], bool]:
    if grades_payload is None:
        ensure_user_storage(data_root, storage_key)
        with open(_student_grades_path(data_root, storage_key), "r", encoding="utf-8") as file:
            payload = json.load(file)
        _normalize_student_points(payload)
        _normalize_student_streak(payload)
        _normalize_weekly_goal(payload)
    else:
        payload = grades_payload
    state = load_state(data_root, storage_key)
    changed = _normalize_weekly_goal(payload)
    week_key = _current_week_key()
    weekly_goal = payload.get("weekly_goal") or {}

    existing_note = next(
        (
            item for item in state.get("notes", [])
            if isinstance(item, dict)
            and isinstance(item.get("result"), dict)
            and str((item.get("result") or {}).get("goal_type") or "").strip() == "weekly_goal"
            and str((item.get("result") or {}).get("week_key") or "").strip() == week_key
        ),
        None,
    )

    if str(weekly_goal.get("week_key") or "").strip() == week_key and existing_note is not None:
        if str(weekly_goal.get("note_id") or "").strip() != str(existing_note.get("id") or "").strip():
            payload["weekly_goal"]["note_id"] = str(existing_note.get("id") or "").strip()
            changed = True
        return payload, changed

    task, subject = _build_weekly_goal_with_ai(payload, state)
    today_date = datetime.now(timezone.utc).date()
    week_end = today_date + timedelta(days=max(0, 7 - today_date.isoweekday()))
    entry = {
        "id": secrets.token_hex(8),
        "source_text": task,
        "saved_at": _utc_now(),
        "result": {
            "category": 1,
            "task": task,
            "date": week_end.isoformat(),
            "goal_type": "weekly_goal",
            "week_key": week_key,
            "points_reward": WEEKLY_GOAL_REWARD_POINTS,
            "subject": subject,
        },
    }
    state["notes"].insert(0, entry)
    save_state(data_root, storage_key, state)
    payload["weekly_goal"] = {
        "week_key": week_key,
        "task": task,
        "subject": subject,
        "points_reward": WEEKLY_GOAL_REWARD_POINTS,
        "note_id": entry["id"],
        "created_at": entry["saved_at"],
    }
    return payload, True


def _save_student_grades(data_root: str, storage_key: str, payload: dict[str, Any]) -> None:
    ensure_user_storage(data_root, storage_key)
    with open(_student_grades_path(data_root, storage_key), "w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=True, indent=2)


def load_student_grades(data_root: str, storage_key: str) -> dict[str, Any]:
    ensure_user_storage(data_root, storage_key)
    with open(_student_grades_path(data_root, storage_key), "r", encoding="utf-8") as file:
        payload = json.load(file)
    changed = _normalize_student_points(payload)
    changed = _normalize_student_streak(payload) or changed
    changed = _normalize_weekly_goal(payload) or changed
    if payload.pop("rating", None) is not None:
        changed = True
    if payload.pop("assistant_prompt", None) is not None:
        changed = True
    refreshed, insights_changed = _refresh_student_grades_insights(payload)
    refreshed, weekly_goal_changed = ensure_weekly_goal_note(data_root, storage_key, refreshed)
    refreshed["points_profile"] = build_points_profile(refreshed.get("points"))
    if changed or insights_changed or weekly_goal_changed:
        _save_student_grades(data_root, storage_key, refreshed)
    return refreshed


def sync_student_homework_rating(data_root: str, storage_key: str, today_iso: str | None = None) -> dict[str, Any]:
    state = load_state(data_root, storage_key)
    state_changed = False

    for homework in state.get("homework", []):
        if _normalize_homework_gamification_fields(homework):
            state_changed = True
        if _normalize_homework_points_value(homework):
            state_changed = True

    if state_changed:
        save_state(data_root, storage_key, state)
    return state


def toggle_student_homework_completion(data_root: str, storage_key: str, homework_id: str) -> tuple[bool, dict[str, Any] | None]:
    state = sync_student_homework_rating(data_root, storage_key)
    grades_payload = load_student_grades(data_root, storage_key)

    state_changed = False
    target_homework: dict[str, Any] | None = None
    total_delta = 0
    streak_changed = False

    for homework in state.get("homework", []):
        if _normalize_homework_gamification_fields(homework):
            state_changed = True
        if _normalize_homework_points_value(homework):
            state_changed = True
        if str(homework.get("id", "")).strip() != str(homework_id or "").strip():
            continue

        target_homework = homework
        next_done = not homework.get("done", False)
        homework["done"] = next_done
        state_changed = True
        points_value = max(1, int(homework.get("points_value", DEFAULT_HOMEWORK_POINTS)))

        if next_done:
            homework["completed_at"] = _utc_now()
            total_delta += points_value
            streak_changed = _apply_streak_completion(grades_payload, datetime.now(timezone.utc).date().isoformat()) or streak_changed
        else:
            homework.pop("completed_at", None)
            total_delta -= points_value
        break

    if target_homework is None:
        return False, None

    points_changed = False
    if total_delta and _apply_student_points_delta(
        grades_payload,
        total_delta,
        "homework_completed" if total_delta > 0 else "homework_reopened",
    ):
        points_changed = True

    if state_changed:
        save_state(data_root, storage_key, state)
    if points_changed or streak_changed:
        grades_payload["points_profile"] = build_points_profile(grades_payload.get("points"))
        _save_student_grades(data_root, storage_key, grades_payload)

    return True, {
        "done": bool(target_homework.get("done", False)),
        "points": grades_payload.get("points", _default_student_points()),
        "points_profile": grades_payload.get("points_profile", build_points_profile(grades_payload.get("points"))),
        "streak": grades_payload.get("streak", _default_student_streak()),
    }


def submit_student_homework(
    data_root: str,
    storage_key: str,
    homework_id: str,
    submission_text: str | None = None,
    file_name: str | None = None,
    file_bytes: bytes | None = None,
) -> tuple[bool, dict[str, Any] | None]:
    state = sync_student_homework_rating(data_root, storage_key)
    grades_payload = load_student_grades(data_root, storage_key)

    state_changed = False
    target_homework: dict[str, Any] | None = None
    total_delta = 0
    streak_changed = False
    submitted_label = str(submission_text or '').strip()
    uploaded_file_name = str(file_name or '').strip()

    for homework in state.get('homework', []):
        if str(homework.get('id', '')).strip() != str(homework_id or '').strip():
            continue
        target_homework = homework
        was_done = bool(homework.get('done', False))
        previous_token = str(homework.get('submitted_file_token') or '').strip()

        if file_bytes is not None and uploaded_file_name:
            stored_name, stored_token = save_homework_submission_file(
                data_root,
                storage_key,
                uploaded_file_name,
                file_bytes,
                previous_token,
            )
            homework['submitted_file_name'] = stored_name
            homework['submitted_file_token'] = stored_token
        elif submitted_label:
            homework['submitted_file_name'] = submitted_label
            homework.pop('submitted_file_token', None)
        elif not str(homework.get('submitted_file_name') or '').strip():
            homework['submitted_file_name'] = 'Решение отправлено'

        homework['done'] = True
        homework['submitted_at'] = _utc_now()
        homework['submitted_text'] = submitted_label or str(homework.get('submitted_file_name') or '').strip()
        state_changed = True

        if not was_done:
            points_value = max(1, int(homework.get('points_value', DEFAULT_HOMEWORK_POINTS)))
            total_delta += points_value
            streak_changed = _apply_streak_completion(grades_payload, datetime.now(timezone.utc).date().isoformat()) or streak_changed
        break

    if target_homework is None:
        return False, None

    points_changed = False
    if total_delta and _apply_student_points_delta(grades_payload, total_delta, 'homework_submitted'):
        points_changed = True

    if state_changed:
        save_state(data_root, storage_key, state)
    if points_changed or streak_changed:
        grades_payload['points_profile'] = build_points_profile(grades_payload.get('points'))
        _save_student_grades(data_root, storage_key, grades_payload)

    return True, {
        'done': bool(target_homework.get('done', False)),
        'submitted_at': str(target_homework.get('submitted_at') or ''),
        'submitted_file_name': str(target_homework.get('submitted_file_name') or ''),
        'submitted_file_token': str(target_homework.get('submitted_file_token') or ''),
        'points': grades_payload.get('points', _default_student_points()),
        'points_profile': grades_payload.get('points_profile', build_points_profile(grades_payload.get('points'))),
        'streak': grades_payload.get('streak', _default_student_streak()),
    }


def get_student_homework_submission(
    data_root: str,
    storage_key: str,
    homework_id: str,
) -> dict[str, Any] | None:
    state = load_state(data_root, storage_key)
    target_id = str(homework_id or "").strip()
    if not target_id:
        return None

    for homework in state.get("homework", []):
        if str(homework.get("id") or "").strip() != target_id:
            continue
        file_name = str(homework.get("submitted_file_name") or "").strip()
        file_token = str(homework.get("submitted_file_token") or "").strip()
        file_path = get_homework_submission_path(data_root, storage_key, file_token)
        if not file_name or not file_token or not file_path:
            return None
        return {
            "file_name": file_name,
            "file_token": file_token,
            "file_path": file_path,
            "submitted_at": str(homework.get("submitted_at") or "").strip(),
            "homework_id": target_id,
        }
    return None

def save_planner_result(data_root: str, storage_key: str, source_text: str, result: dict[str, Any]) -> dict[str, Any] | None:
    state = load_state(data_root, storage_key)
    entry = {
        "id": secrets.token_hex(8),
        "source_text": source_text,
        "saved_at": _utc_now(),
        "result": result,
    }

    if result.get("category") == 1:
        state["notes"].insert(0, entry)
    elif result.get("category") == 2:
        state["searches"].insert(0, entry)
    else:
        return None

    save_state(data_root, storage_key, state)
    return entry


def create_teacher_homework_assignment(
    data_root: str,
    teacher_storage_key: str,
    students: list[dict[str, Any]],
    class_name: str,
    subject: str | None,
    task: str,
    date: str | None,
    points_value: int = DEFAULT_HOMEWORK_POINTS,
    teacher_name: str | None = None,
) -> dict[str, Any]:
    cleaned_class_name = str(class_name or "").strip()
    cleaned_subject = str(subject or "").strip()
    cleaned_task = str(task or "").strip()
    cleaned_date = str(date or "").strip() or None
    cleaned_teacher_name = str(teacher_name or "").strip()
    cleaned_points_value = max(1, int(points_value or DEFAULT_HOMEWORK_POINTS))

    if not cleaned_class_name:
        raise ValueError("Не указан класс")
    if not cleaned_task:
        raise ValueError("Не указан текст домашнего задания")
    if not cleaned_date:
        raise ValueError("Не указана дата домашнего задания")

    teacher_state = load_state(data_root, teacher_storage_key)
    existing_teacher = next(
        (
            item for item in teacher_state.get("homework", [])
            if item.get("source") == "teacher"
            and str(item.get("class_name", "")).strip() == cleaned_class_name
            and str(item.get("subject", "")).strip() == cleaned_subject
            and str(item.get("task", "")).strip() == cleaned_task
            and str(item.get("date", "")).strip() == cleaned_date
        ),
        None,
    )

    total_count = len(students)
    if existing_teacher is None:
        teacher_entry = {
            "id": f"teacher-homework-{secrets.token_hex(8)}",
            "source": "teacher",
            "class_name": cleaned_class_name,
            "subject": cleaned_subject,
            "task": cleaned_task,
            "date": cleaned_date,
            "done": False,
            "volume": "medium",
            "priority": "medium",
            "teacher_reviewed": False,
            "teacher_progress_percent": 0,
            "teacher_checked_count": 0,
            "teacher_total_count": total_count,
            "teacher_action_label": "Проверить загруженные решения",
            "created_at": _utc_now(),
            "points_value": cleaned_points_value,
        }
        teacher_state["homework"].insert(0, teacher_entry)
        save_state(data_root, teacher_storage_key, teacher_state)
    else:
        teacher_entry = existing_teacher
        teacher_entry["teacher_total_count"] = total_count
        teacher_entry["points_value"] = cleaned_points_value
        save_state(data_root, teacher_storage_key, teacher_state)

    created_students = 0
    for student in students:
        storage_key = str(student.get("storage_key", "")).strip()
        if not storage_key:
            continue

        student_state = load_state(data_root, storage_key)
        duplicate = next(
            (
                item for item in student_state.get("homework", [])
                if item.get("source") == "teacher"
                and str(item.get("class_name", "")).strip() == cleaned_class_name
                and str(item.get("subject", "")).strip() == cleaned_subject
                and str(item.get("task", "")).strip() == cleaned_task
                and str(item.get("date", "")).strip() == cleaned_date
            ),
            None,
        )
        if duplicate is not None:
            continue

        student_state["homework"].insert(0, {
            "id": f"student-homework-{secrets.token_hex(8)}",
            "kind": "homework",
            "source": "teacher",
            "assigned_by": cleaned_teacher_name,
            "class_name": cleaned_class_name,
            "subject": cleaned_subject,
            "task": cleaned_task,
            "description": cleaned_task,
            "date": cleaned_date,
            "done": False,
            "rating_reward_applied": False,
            "rating_penalty_applied": False,
            "volume": "medium",
            "priority": "medium",
            "created_at": _utc_now(),
            "points_value": cleaned_points_value,
        })
        save_state(data_root, storage_key, student_state)
        created_students += 1

    return {
        "teacher_homework": teacher_entry,
        "created_students": created_students,
        "total_students": total_count,
    }


def delete_teacher_homework_assignment(
    data_root: str,
    teacher_storage_key: str,
    homework_id: str,
    students: list[dict[str, Any]],
) -> dict[str, Any] | None:
    target_id = str(homework_id or "").strip()
    if not target_id:
        return None

    teacher_state = load_state(data_root, teacher_storage_key)
    target_homework = next(
        (
            item for item in teacher_state.get("homework", [])
            if str(item.get("id") or "").strip() == target_id and str(item.get("source") or "").strip() == "teacher"
        ),
        None,
    )
    if target_homework is None:
        return None

    class_name = str(target_homework.get("class_name") or "").strip()
    subject = str(target_homework.get("subject") or "").strip()
    task = str(target_homework.get("task") or "").strip()
    due_date = str(target_homework.get("date") or "").strip()

    teacher_state["homework"] = [
        item for item in teacher_state.get("homework", [])
        if str(item.get("id") or "").strip() != target_id
    ]
    removed_seed_ids = [str(item).strip() for item in teacher_state.get("removed_seed_homework_ids", []) if str(item).strip()]
    if target_id.startswith("seed-homework-") and target_id not in removed_seed_ids:
        removed_seed_ids.append(target_id)
    teacher_state["removed_seed_homework_ids"] = removed_seed_ids
    save_state(data_root, teacher_storage_key, teacher_state)

    removed_students = 0
    for student in students:
        storage_key = str(student.get("storage_key") or "").strip()
        if not storage_key:
            continue

        student_state = load_state(data_root, storage_key)
        before_count = len(student_state.get("homework", []))
        student_state["homework"] = [
            item for item in student_state.get("homework", [])
            if not (
                str(item.get("source") or "").strip() == "teacher"
                and str(item.get("class_name") or "").strip() == class_name
                and str(item.get("subject") or "").strip() == subject
                and str(item.get("task") or "").strip() == task
                and str(item.get("date") or "").strip() == due_date
            )
        ]
        if len(student_state.get("homework", [])) != before_count:
            removed_students += 1
            save_state(data_root, storage_key, student_state)

    return {
        "id": target_id,
        "class_name": class_name,
        "subject": subject,
        "task": task,
        "date": due_date,
        "removed_students": removed_students,
    }


def complete_note(data_root: str, storage_key: str, note_id: str) -> dict[str, Any] | None:
    state = load_state(data_root, storage_key)
    notes = state.get("notes", [])
    note = next((item for item in notes if item.get("id") == note_id), None)
    if note is None:
        return None

    state["notes"] = [item for item in notes if item.get("id") != note_id]
    save_state(data_root, storage_key, state)

    archive = load_completed_tasks(data_root, storage_key)
    archived_note = _normalize_archive_entry(
        {
            **note,
            "kind": "note",
            "status": "completed",
            "title": "Личное задание",
            "description": (note.get("result") or {}).get("task") or note.get("source_text"),
            "date": (note.get("result") or {}).get("date"),
            "archived_at": _utc_now(),
        },
        "completed",
    )
    archive["completed"].insert(0, archived_note)
    save_completed_tasks(data_root, storage_key, archive)
    return archived_note


def save_note_subtasks(
    data_root: str,
    storage_key: str,
    note_id: str,
    subtasks: list[str],
) -> dict[str, Any] | None:
    state = load_state(data_root, storage_key)
    cleaned_subtasks = []
    for item in (subtasks or []):
        value = str(item).strip()
        if not value:
            continue
        cleaned_subtasks.append({
            "text": value,
            "done": False,
        })

    for note in state.get("notes", []):
        if str(note.get("id") or "").strip() != str(note_id or "").strip():
            continue
        result = note.get("result")
        if not isinstance(result, dict):
            result = {}
            note["result"] = result
        result["subtasks"] = cleaned_subtasks
        result["subtasks_generated_at"] = _utc_now()
        save_state(data_root, storage_key, state)
        return note
    return None


def toggle_note_subtask(
    data_root: str,
    storage_key: str,
    note_id: str,
    subtask_index: int,
) -> dict[str, Any] | None:
    state = load_state(data_root, storage_key)

    for note in state.get("notes", []):
        if str(note.get("id") or "").strip() != str(note_id or "").strip():
            continue
        result = note.get("result")
        if not isinstance(result, dict):
            return None

        subtasks = result.get("subtasks")
        if not isinstance(subtasks, list):
            return None

        normalized_subtasks: list[dict[str, Any]] = []
        for item in subtasks:
            if isinstance(item, dict):
                text = str(item.get("text") or "").strip()
                done = bool(item.get("done", False))
            else:
                text = str(item or "").strip()
                done = False
            if text:
                normalized_subtasks.append({"text": text, "done": done})

        if subtask_index < 0 or subtask_index >= len(normalized_subtasks):
            return None

        normalized_subtasks[subtask_index]["done"] = not bool(normalized_subtasks[subtask_index].get("done", False))
        result["subtasks"] = normalized_subtasks
        save_state(data_root, storage_key, state)
        return note

    return None


def _parse_iso_date(raw_value: Any) -> date | None:
    value = str(raw_value or "").strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None


def _notification_severity(score: int) -> str:
    if score >= 90:
        return "critical"
    if score >= 70:
        return "high"
    if score >= 45:
        return "medium"
    return "low"


def _notification_due_text(days_left: int | None) -> str:
    if days_left is None:
        return "без точного срока"
    if days_left < 0:
        overdue_days = abs(days_left)
        return f"просрочено на {overdue_days} дн." if overdue_days != 1 else "просрочено на 1 день"
    if days_left == 0:
        return "срок сегодня"
    if days_left == 1:
        return "срок завтра"
    return f"срок через {days_left} дн."


def _fallback_notification_message(item: dict[str, Any]) -> str:
    title = str(item.get("title") or "Задание").strip()
    due_text = str(item.get("due_text") or "").strip()
    severity = str(item.get("severity") or "low").strip()
    if severity == "critical":
        return f"Срочно вернись к задаче «{title}»: {due_text}. Лучше закрыть ее как можно скорее."
    if severity == "high":
        return f"Не откладывай «{title}»: {due_text}. Стоит заняться этим в ближайшее время."
    if severity == "medium":
        return f"Держи в фокусе «{title}»: {due_text}. Хорошо бы запланировать выполнение заранее."
    return f"Напоминание по задаче «{title}»: {due_text}. Можно спокойно запланировать ее заранее."


def _ai_notification_messages(items: list[dict[str, Any]]) -> dict[str, str]:
    if not items:
        return {}
    try:
        import ollama  # type: ignore
    except Exception:
        return {}

    prompt_items = [
        {
            "source_id": item.get("source_id"),
            "type": item.get("type"),
            "title": item.get("title"),
            "due_text": item.get("due_text"),
            "severity": item.get("severity"),
            "score": item.get("score"),
            "subject": item.get("subject"),
        }
        for item in items[:8]
    ]
    system_prompt = (
        "Ты пишешь короткие учебные уведомления для школьника. "
        "Для каждого элемента верни одну фразу на русском, которая мягко, но ясно напоминает о срочности. "
        "Верни только JSON вида "
        "{\"notifications\":[{\"source_id\":\"...\",\"message\":\"...\"}]}"
    )
    try:
        response = ollama.chat(
            model=os.getenv("OLLAMA_MODEL", "qwen2.5:3b"),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(prompt_items, ensure_ascii=False)},
            ],
            format="json",
            options={"temperature": 0.3},
        )
        raw = (response.get("message") or {}).get("content") or "{}"
        parsed = json.loads(raw)
        notifications = parsed.get("notifications")
        if not isinstance(notifications, list):
            return {}
        result: dict[str, str] = {}
        for item in notifications:
            if not isinstance(item, dict):
                continue
            source_id = str(item.get("source_id") or "").strip()
            message = str(item.get("message") or "").strip()
            if source_id and message:
                result[source_id] = message
        return result
    except Exception:
        return {}


def build_student_ai_notifications(
    data_root: str,
    storage_key: str,
    today_iso: str | None = None,
) -> list[dict[str, Any]]:
    today_date = _parse_iso_date(today_iso) or datetime.now(timezone.utc).date()
    state = load_state(data_root, storage_key)
    items: list[dict[str, Any]] = []

    for homework in state.get("homework", []):
        if not isinstance(homework, dict) or bool(homework.get("done")):
            continue
        due_date = _parse_iso_date(homework.get("date"))
        days_left = (due_date - today_date).days if due_date else None
        score = 25
        if days_left is None:
            score = 30
        elif days_left < 0:
            score = 100
        elif days_left == 0:
            score = 90
        elif days_left == 1:
            score = 78
        elif days_left <= 3:
            score = 60
        elif days_left <= 7:
            score = 40
        score += min(15, max(0, int(homework.get("points_value") or 1) * 2))
        title = f"{str(homework.get('subject') or 'Домашнее задание').strip()}: {str(homework.get('task') or homework.get('description') or '').strip()}".strip(": ")
        items.append(
            {
                "source_id": str(homework.get("id") or "").strip(),
                "type": "homework",
                "title": title or "Домашнее задание",
                "date": due_date.isoformat() if due_date else "",
                "days_left": days_left,
                "due_text": _notification_due_text(days_left),
                "score": min(score, 100),
                "severity": _notification_severity(min(score, 100)),
                "subject": str(homework.get("subject") or "").strip(),
            }
        )

    for note in state.get("notes", []):
        if not isinstance(note, dict):
            continue
        result = note.get("result") if isinstance(note.get("result"), dict) else {}
        if str(result.get("goal_type") or "").strip() == "weekly_goal":
            continue
        due_date = _parse_iso_date(result.get("date"))
        title = str(result.get("task") or note.get("source_text") or "").strip()
        if not title:
            continue
        subtasks = result.get("subtasks")
        progress_bonus = 0
        if isinstance(subtasks, list) and subtasks:
            total = 0
            done = 0
            for item in subtasks:
                if isinstance(item, dict):
                    text = str(item.get("text") or "").strip()
                    if not text:
                        continue
                    total += 1
                    if bool(item.get("done", False)):
                        done += 1
                else:
                    if str(item or "").strip():
                        total += 1
            if total:
                progress_bonus = max(0, 10 - round((done / total) * 10))
        days_left = (due_date - today_date).days if due_date else None
        score = 18 + progress_bonus
        if days_left is None:
            score = max(score, 22)
        elif days_left < 0:
            score = 95
        elif days_left == 0:
            score = max(score, 82)
        elif days_left == 1:
            score = max(score, 68)
        elif days_left <= 3:
            score = max(score, 50)
        items.append(
            {
                "source_id": str(note.get("id") or "").strip(),
                "type": "note",
                "title": title,
                "date": due_date.isoformat() if due_date else "",
                "days_left": days_left,
                "due_text": _notification_due_text(days_left),
                "score": min(score, 100),
                "severity": _notification_severity(min(score, 100)),
                "subject": "",
            }
        )

    items.sort(key=lambda item: (-int(item.get("score") or 0), str(item.get("date") or ""), str(item.get("title") or "")))
    ai_messages = _ai_notification_messages(items[:8])
    notifications: list[dict[str, Any]] = []
    for item in items[:8]:
        source_id = str(item.get("source_id") or "").strip()
        notifications.append(
            {
                **item,
                "message": ai_messages.get(source_id) or _fallback_notification_message(item),
            }
        )
    return notifications


def archive_overdue_notes(data_root: str, storage_key: str, today_iso: str) -> dict[str, list[dict[str, Any]]]:
    state = load_state(data_root, storage_key)
    archive = load_completed_tasks(data_root, storage_key)
    remaining_notes: list[dict[str, Any]] = []
    changed = False

    for note in state.get("notes", []):
        result = note.get("result") or {}
        note_date = str(result.get("date") or "").strip()
        if note_date and note_date < today_iso:
            if not any(item.get("id") == note.get("id") for item in archive["missed"]):
                archive["missed"].insert(
                    0,
                    _normalize_archive_entry(
                        {
                            **note,
                            "kind": "note",
                            "status": "missed",
                            "title": "Личное задание",
                            "description": result.get("task") or note.get("source_text"),
                            "date": note_date,
                            "archived_at": _utc_now(),
                        },
                        "missed",
                    ),
                )
            changed = True
            continue
        remaining_notes.append(note)

    if changed:
        state["notes"] = remaining_notes
        save_state(data_root, storage_key, state)
        save_completed_tasks(data_root, storage_key, archive)

    return archive


def move_archive_item_to_trash(data_root: str, storage_key: str, section: str, item_id: str) -> dict[str, list[dict[str, Any]]]:
    archive = load_completed_tasks(data_root, storage_key)
    if section not in {"completed", "missed", "trash"}:
        return archive

    items = archive.get(section, [])
    target = next((item for item in items if item.get("id") == item_id), None)
    if target is None:
        return archive

    archive[section] = [item for item in items if item.get("id") != item_id]
    if section != "trash":
        archive["trash"].insert(0, {**target, "status": "trash", "archived_at": _utc_now()})
    save_completed_tasks(data_root, storage_key, archive)
    return archive


def clear_archive_trash(data_root: str, storage_key: str) -> dict[str, list[dict[str, Any]]]:
    archive = load_completed_tasks(data_root, storage_key)
    archive["trash"] = []
    save_completed_tasks(data_root, storage_key, archive)
    return archive


def list_chat_sessions(data_root: str, storage_key: str) -> list[dict[str, Any]]:
    state = load_state(data_root, storage_key)
    sessions = state.get("chat_sessions", [])
    return sorted(sessions, key=lambda item: item.get("updated_at", ""), reverse=True)


def get_chat_session(data_root: str, storage_key: str, chat_id: str) -> dict[str, Any] | None:
    ensure_user_storage(data_root, storage_key)
    path = _chat_path(data_root, storage_key, chat_id)
    if not os.path.exists(path):
        return None

    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def _save_chat_session(data_root: str, storage_key: str, session: dict[str, Any]) -> None:
    ensure_user_storage(data_root, storage_key)
    path = _chat_path(data_root, storage_key, session["chat_id"])
    with open(path, "w", encoding="utf-8") as file:
        json.dump(session, file, ensure_ascii=False, indent=2)


def _upsert_chat_summary(data_root: str, storage_key: str, summary: dict[str, Any]) -> None:
    state = load_state(data_root, storage_key)
    sessions = state.get("chat_sessions", [])
    sessions = [item for item in sessions if item.get("chat_id") != summary["chat_id"]]
    sessions.insert(0, summary)
    state["chat_sessions"] = sessions
    save_state(data_root, storage_key, state)


def save_chat_exchange(
    data_root: str,
    storage_key: str,
    user_message: str,
    assistant_message: str,
    chat_id: str | None = None,
) -> dict[str, Any]:
    now = _utc_now()
    session = get_chat_session(data_root, storage_key, chat_id) if chat_id else None

    if session is None:
        session = {
            "chat_id": chat_id or secrets.token_hex(10),
            "title": user_message.strip()[:48] or "Новый чат",
            "created_at": now,
            "updated_at": now,
            "messages": [],
        }

    session["messages"].extend(
        [
            {"role": "user", "content": user_message, "created_at": now},
            {"role": "assistant", "content": assistant_message, "created_at": _utc_now()},
        ]
    )
    session["updated_at"] = _utc_now()

    _save_chat_session(data_root, storage_key, session)
    _upsert_chat_summary(
        data_root,
        storage_key,
        {
            "chat_id": session["chat_id"],
            "title": session["title"],
            "created_at": session["created_at"],
            "updated_at": session["updated_at"],
        },
    )
    return session
