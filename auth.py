import hashlib
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any


SESSION_TTL_DAYS = 7


def _connect(db_path: str) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _hash_password(password: str, salt: bytes | None = None) -> str:
    salt_bytes = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt_bytes, 120000)
    return f"{salt_bytes.hex()}${digest.hex()}"


def _verify_password(password: str, stored_hash: str) -> bool:
    try:
        salt_hex, _ = stored_hash.split("$", 1)
    except ValueError:
        return False

    check_hash = _hash_password(password, bytes.fromhex(salt_hex))
    return secrets.compare_digest(check_hash, stored_hash)


def init_database(db_path: str) -> None:
    with _connect(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL,
                display_name TEXT NOT NULL,
                storage_key TEXT,
                class_name TEXT,
                managed_classes TEXT
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            """
        )

        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(users)").fetchall()
        }
        if "storage_key" not in columns:
            connection.execute("ALTER TABLE users ADD COLUMN storage_key TEXT")
        if "class_name" not in columns:
            connection.execute("ALTER TABLE users ADD COLUMN class_name TEXT")
        if "managed_classes" not in columns:
            connection.execute("ALTER TABLE users ADD COLUMN managed_classes TEXT")

        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_storage_key ON users(storage_key)"
        )

        users = (
            ("student", "student123", "student", "Илья Смирнов", "10 А", None),
            ("student2", "student123", "student", "Анна Волкова", "10 Б", None),
            ("student3", "student123", "student", "Егор Ковалев", "11 А", None),
            ("teacher", "teacher123", "teacher", "Учитель", None, "10 А, 10 Б, 11 А"),
            ("admin", "admin123", "admin", "Администратор", None, None),
        )

        for username, password, role, display_name, class_name, managed_classes in users:
            connection.execute(
                """
                INSERT INTO users (username, password_hash, role, display_name, storage_key, class_name, managed_classes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(username) DO NOTHING
                """,
                (
                    username,
                    _hash_password(password),
                    role,
                    display_name,
                    secrets.token_hex(16),
                    class_name,
                    managed_classes,
                ),
            )

        connection.execute(
            "UPDATE users SET managed_classes = COALESCE(NULLIF(managed_classes, ''), ?) WHERE role = 'teacher'",
            ("10 А, 10 Б, 11 А",),
        )
        connection.execute(
            "UPDATE users SET class_name = COALESCE(NULLIF(class_name, ''), ?) WHERE role = 'student'",
            ("10 А",),
        )

        student_defaults = {
            "student": ("Илья Смирнов", "10 А"),
            "student2": ("Анна Волкова", "10 Б"),
            "student3": ("Егор Ковалев", "11 А"),
            "student4": ("Мария Орлова", "10 А"),
            "student5": ("Иван Петров", "10 А"),
        }
        for username, (display_name, class_name) in student_defaults.items():
            connection.execute(
                """
                UPDATE users
                SET display_name = ?, class_name = ?
                WHERE username = ? AND role = 'student'
                """,
                (display_name, class_name, username),
            )

        rows = connection.execute(
            "SELECT id FROM users WHERE storage_key IS NULL OR storage_key = ''"
        ).fetchall()
        for row in rows:
            connection.execute(
                "UPDATE users SET storage_key = ? WHERE id = ?",
                (secrets.token_hex(16), row["id"]),
            )

        connection.commit()


def authenticate_user(db_path: str, username: str, password: str) -> dict[str, Any] | None:
    with _connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT id, username, password_hash, role, display_name, storage_key
            FROM users
            WHERE username = ?
            """,
            (username,),
        ).fetchone()

    if row is None or not _verify_password(password, row["password_hash"]):
        return None

    return {
        "id": row["id"],
        "username": row["username"],
        "role": row["role"],
        "display_name": row["display_name"],
        "storage_key": row["storage_key"],
    }


def create_session(db_path: str, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    expires_at = (_utc_now() + timedelta(days=SESSION_TTL_DAYS)).isoformat()

    with _connect(db_path) as connection:
        connection.execute(
            "INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
            (token, user_id, expires_at),
        )
        connection.commit()

    return token


def get_user_by_session(db_path: str, token: str | None) -> dict[str, Any] | None:
    if not token:
        return None

    now_iso = _utc_now().isoformat()

    with _connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT users.id, users.username, users.role, users.display_name, users.storage_key, sessions.expires_at
            FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token = ?
            """,
            (token,),
        ).fetchone()

        if row is None:
            return None

        if row["expires_at"] <= now_iso:
            connection.execute("DELETE FROM sessions WHERE token = ?", (token,))
            connection.commit()
            return None

    return {
        "id": row["id"],
        "username": row["username"],
        "role": row["role"],
        "display_name": row["display_name"],
        "storage_key": row["storage_key"],
    }


def delete_session(db_path: str, token: str | None) -> None:
    if not token:
        return

    with _connect(db_path) as connection:
        connection.execute("DELETE FROM sessions WHERE token = ?", (token,))
        connection.commit()


def list_school_users(db_path: str) -> dict[str, list[dict[str, Any]]]:
    with _connect(db_path) as connection:
        teachers = [
            {
                "id": row["id"],
                "display_name": row["display_name"],
                "username": row["username"],
                "managed_classes": row["managed_classes"] or "",
            }
            for row in connection.execute(
                """
                SELECT id, display_name, username, managed_classes
                FROM users
                WHERE role = 'teacher'
                ORDER BY display_name COLLATE NOCASE, username COLLATE NOCASE
                """
            ).fetchall()
        ]
        students = [
            {
                "id": row["id"],
                "display_name": row["display_name"],
                "username": row["username"],
                "class_name": row["class_name"] or "",
            }
            for row in connection.execute(
                """
                SELECT id, display_name, username, class_name
                FROM users
                WHERE role = 'student'
                ORDER BY display_name COLLATE NOCASE, username COLLATE NOCASE
                """
            ).fetchall()
        ]
    return {"teachers": teachers, "students": students}


def list_students_for_classes(db_path: str, class_names: list[str]) -> list[dict[str, Any]]:
    cleaned = [str(name or "").strip() for name in class_names if str(name or "").strip()]
    if not cleaned:
        return []

    placeholders = ", ".join("?" for _ in cleaned)
    with _connect(db_path) as connection:
        rows = connection.execute(
            f"""
            SELECT id, username, display_name, storage_key, class_name
            FROM users
            WHERE role = 'student' AND class_name IN ({placeholders})
            ORDER BY class_name COLLATE NOCASE, display_name COLLATE NOCASE, username COLLATE NOCASE
            """,
            tuple(cleaned),
        ).fetchall()

    return [
        {
            "id": row["id"],
            "username": row["username"],
            "display_name": row["display_name"],
            "storage_key": row["storage_key"],
            "class_name": row["class_name"] or "",
        }
        for row in rows
    ]


def get_teacher_managed_classes(db_path: str, username: str) -> list[str]:
    cleaned_username = str(username or "").strip()
    if not cleaned_username:
        return []

    with _connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT managed_classes
            FROM users
            WHERE role = 'teacher' AND username = ?
            """,
            (cleaned_username,),
        ).fetchone()

    if row is None:
        return []

    raw = str(row["managed_classes"] or "")
    return [item.strip() for item in raw.split(",") if item.strip()]


def create_student_user(
    db_path: str,
    display_name: str,
    class_name: str,
    username: str,
    password: str,
) -> dict[str, Any]:
    cleaned_display_name = display_name.strip()
    cleaned_class_name = class_name.strip()
    cleaned_username = username.strip()
    cleaned_password = password.strip()

    if not cleaned_display_name:
        raise ValueError("Введите имя ученика")
    if not cleaned_class_name:
        raise ValueError("Введите класс")
    if not cleaned_username:
        raise ValueError("Введите логин")
    if not cleaned_password:
        raise ValueError("Введите пароль")

    with _connect(db_path) as connection:
        existing = connection.execute(
            "SELECT id FROM users WHERE username = ?",
            (cleaned_username,),
        ).fetchone()
        if existing is not None:
            raise ValueError("Такой логин уже существует")

        cursor = connection.execute(
            """
            INSERT INTO users (username, password_hash, role, display_name, storage_key, class_name)
            VALUES (?, ?, 'student', ?, ?, ?)
            """,
            (
                cleaned_username,
                _hash_password(cleaned_password),
                cleaned_display_name,
                secrets.token_hex(16),
                cleaned_class_name,
            ),
        )
        connection.commit()
        user_id = cursor.lastrowid

    return {
        "id": user_id,
        "display_name": cleaned_display_name,
        "username": cleaned_username,
        "class_name": cleaned_class_name,
    }


def create_teacher_user(
    db_path: str,
    display_name: str,
    managed_classes: str,
    username: str,
    password: str,
) -> dict[str, Any]:
    cleaned_display_name = display_name.strip()
    cleaned_managed_classes = managed_classes.strip()
    cleaned_username = username.strip()
    cleaned_password = password.strip()

    if not cleaned_display_name:
        raise ValueError("Введите имя учителя")
    if not cleaned_managed_classes:
        raise ValueError("Введите классы учителя")
    if not cleaned_username:
        raise ValueError("Введите логин")
    if not cleaned_password:
        raise ValueError("Введите пароль")

    with _connect(db_path) as connection:
        existing = connection.execute(
            "SELECT id FROM users WHERE username = ?",
            (cleaned_username,),
        ).fetchone()
        if existing is not None:
            raise ValueError("Такой логин уже существует")

        cursor = connection.execute(
            """
            INSERT INTO users (username, password_hash, role, display_name, storage_key, managed_classes)
            VALUES (?, ?, 'teacher', ?, ?, ?)
            """,
            (
                cleaned_username,
                _hash_password(cleaned_password),
                cleaned_display_name,
                secrets.token_hex(16),
                cleaned_managed_classes,
            ),
        )
        connection.commit()
        user_id = cursor.lastrowid

    return {
        "id": user_id,
        "display_name": cleaned_display_name,
        "username": cleaned_username,
        "managed_classes": cleaned_managed_classes,
    }


def delete_student_user(db_path: str, user_id: int) -> bool:
    with _connect(db_path) as connection:
        row = connection.execute(
            "SELECT id FROM users WHERE id = ? AND role = 'student'",
            (user_id,),
        ).fetchone()
        if row is None:
            return False
        connection.execute("DELETE FROM users WHERE id = ?", (user_id,))
        connection.commit()
    return True


def delete_teacher_user(db_path: str, user_id: int) -> bool:
    with _connect(db_path) as connection:
        row = connection.execute(
            "SELECT id FROM users WHERE id = ? AND role = 'teacher'",
            (user_id,),
        ).fetchone()
        if row is None:
            return False
        connection.execute("DELETE FROM users WHERE id = ?", (user_id,))
        connection.commit()
    return True
