"""SQLite storage cho danh sách subscriber và các job đã gửi."""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from config import DB_PATH

log = logging.getLogger(__name__)


def _get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Khởi tạo bảng nếu chưa có."""
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS subscribers (
                chat_id INTEGER PRIMARY KEY,
                subscribed_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sent_jobs (
                job_id TEXT PRIMARY KEY,
                sent_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # ID tin nhắn thống kê gần nhất của từng chat, để hôm sau xoá đi
        # trước khi gửi bản mới (giữ chat gọn, chỉ còn 1 tin thống kê).
        conn.execute("""
            CREATE TABLE IF NOT EXISTS last_digest (
                chat_id    INTEGER PRIMARY KEY,
                message_id INTEGER NOT NULL,
                sent_at    TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
    log.info("Database initialized at %s", DB_PATH)


def add_subscriber(chat_id: int) -> None:
    with _get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO subscribers (chat_id) VALUES (?)",
            (chat_id,)
        )
        conn.commit()


def remove_subscriber(chat_id: int) -> None:
    with _get_conn() as conn:
        conn.execute("DELETE FROM subscribers WHERE chat_id = ?", (chat_id,))
        conn.commit()


def get_all_subscribers() -> list[int]:
    with _get_conn() as conn:
        rows = conn.execute("SELECT chat_id FROM subscribers").fetchall()
    return [r["chat_id"] for r in rows]


def count_subscribers() -> int:
    with _get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) as cnt FROM subscribers").fetchone()
    return row["cnt"] if row else 0


def filter_unsent(jobs: list) -> list:
    """Trả về các job chưa từng gửi, giữ nguyên thứ tự điểm."""
    if not jobs:
        return []
    ids = [j.job_id for j in jobs]
    placeholders = ",".join("?" * len(ids))
    with _get_conn() as conn:
        rows = conn.execute(
            f"SELECT job_id FROM sent_jobs WHERE job_id IN ({placeholders})",
            ids,
        ).fetchall()
    sent = {r["job_id"] for r in rows}
    return [j for j in jobs if j.job_id not in sent]


def mark_sent(jobs: list) -> None:
    """Ghi nhận các job vừa gửi để hôm sau không gửi lại."""
    if not jobs:
        return
    with _get_conn() as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO sent_jobs (job_id) VALUES (?)",
            [(j.job_id,) for j in jobs],
        )
        conn.commit()


def get_last_digest(chat_id: int) -> int | None:
    """ID tin nhắn thống kê gần nhất đã gửi cho chat này (None nếu chưa có)."""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT message_id FROM last_digest WHERE chat_id = ?", (chat_id,)
        ).fetchone()
    return row["message_id"] if row else None


def set_last_digest(chat_id: int, message_id: int) -> None:
    """Ghi nhận tin nhắn thống kê vừa gửi, thay thế bản ghi cũ của chat đó."""
    with _get_conn() as conn:
        conn.execute(
            "INSERT INTO last_digest (chat_id, message_id, sent_at) "
            "VALUES (?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(chat_id) DO UPDATE SET "
            "message_id = excluded.message_id, sent_at = excluded.sent_at",
            (chat_id, message_id),
        )
        conn.commit()


def clear_last_digest(chat_id: int) -> None:
    """Bỏ bản ghi tin nhắn cũ (dùng khi Telegram báo không xoá được nữa)."""
    with _get_conn() as conn:
        conn.execute("DELETE FROM last_digest WHERE chat_id = ?", (chat_id,))
        conn.commit()


def purge_old_sent(days: int = 60) -> int:
    """Xoá lịch sử cũ để DB không phình mãi. Trả về số dòng đã xoá."""
    with _get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM sent_jobs WHERE sent_at < datetime('now', ?)",
            (f"-{days} days",),
        )
        conn.commit()
        return cur.rowcount
