from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


class Database:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS users ("
                "user_id INTEGER PRIMARY KEY, username TEXT, name TEXT, phone TEXT, "
                "created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
            )
            c.execute(
                "CREATE TABLE IF NOT EXISTS requests ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, name TEXT, phone TEXT, "
                "config TEXT, total TEXT, status TEXT DEFAULT 'new', address TEXT, "
                "dedupe_key TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
            )
            c.execute(
                "CREATE TABLE IF NOT EXISTS drafts ("
                "user_id INTEGER PRIMARY KEY, payload TEXT NOT NULL, "
                "updated_at TEXT DEFAULT CURRENT_TIMESTAMP)"
            )
            cols = {r[1] for r in c.execute("PRAGMA table_info(requests)").fetchall()}
            if "status" not in cols:
                c.execute("ALTER TABLE requests ADD COLUMN status TEXT DEFAULT 'new'")
            if "address" not in cols:
                c.execute("ALTER TABLE requests ADD COLUMN address TEXT")
            if "dedupe_key" not in cols:
                c.execute("ALTER TABLE requests ADD COLUMN dedupe_key TEXT")
            # Старые версии могли создать одинаковые заявки до появления
            # атомарной защиты. Оставляем последнюю запись каждой пары
            # (user_id, dedupe_key), затем ставим уникальный частичный индекс.
            c.execute(
                "DELETE FROM requests "
                "WHERE dedupe_key IS NOT NULL AND dedupe_key <> '' "
                "AND id NOT IN ("
                "SELECT MAX(id) FROM requests "
                "WHERE dedupe_key IS NOT NULL AND dedupe_key <> '' "
                "GROUP BY user_id, dedupe_key"
                ")"
            )
            c.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_requests_user_dedupe_unique "
                "ON requests(user_id, dedupe_key) WHERE dedupe_key <> ''"
            )
            c.execute("CREATE INDEX IF NOT EXISTS idx_requests_user ON requests(user_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_requests_created ON requests(created_at)")

    def save_request_atomic(
        self,
        user_id: int,
        name: str,
        phone: str,
        config: str,
        total: str,
        address: str = "",
        status: str = "new",
        dedupe_key: str = "",
    ) -> tuple[int, bool]:
        """Insert a request atomically and return (request_id, created)."""
        with sqlite3.connect(self.path, timeout=30) as c:
            try:
                cur = c.execute(
                    "INSERT INTO requests(user_id,name,phone,config,total,status,address,dedupe_key) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (user_id, name, phone, config, total, status, address, dedupe_key),
                )
                return int(cur.lastrowid), True
            except sqlite3.IntegrityError:
                if not dedupe_key:
                    raise
                row = c.execute(
                    "SELECT id FROM requests WHERE user_id=? AND dedupe_key=? "
                    "ORDER BY id DESC LIMIT 1",
                    (user_id, dedupe_key),
                ).fetchone()
                if row is None:
                    raise
                return int(row[0]), False

    def save_request(
        self,
        user_id: int,
        name: str,
        phone: str,
        config: str,
        total: str,
        address: str = "",
        status: str = "new",
        dedupe_key: str = "",
    ) -> int:
        request_id, _ = self.save_request_atomic(
            user_id, name, phone, config, total, address, status, dedupe_key
        )
        return request_id

    def recent_duplicate(self, user_id: int, dedupe_key: str, seconds: int = 900) -> int | None:
        if not dedupe_key:
            return None
        with sqlite3.connect(self.path) as c:
            row = c.execute(
                "SELECT id FROM requests "
                "WHERE user_id=? AND dedupe_key=? "
                "AND created_at >= datetime('now', ?) "
                "ORDER BY id DESC LIMIT 1",
                (user_id, dedupe_key, f"-{int(seconds)} seconds"),
            ).fetchone()
        return int(row[0]) if row else None

    def save_draft(self, user_id: int, payload: str) -> None:
        with sqlite3.connect(self.path) as c:
            c.execute(
                "INSERT INTO drafts(user_id,payload,updated_at) VALUES(?,?,CURRENT_TIMESTAMP) "
                "ON CONFLICT(user_id) DO UPDATE SET payload=excluded.payload, updated_at=CURRENT_TIMESTAMP",
                (user_id, payload),
            )

    def load_draft(self, user_id: int) -> str | None:
        with sqlite3.connect(self.path) as c:
            row = c.execute("SELECT payload FROM drafts WHERE user_id=?", (user_id,)).fetchone()
        return row[0] if row else None

    def clear_draft(self, user_id: int) -> None:
        with sqlite3.connect(self.path) as c:
            c.execute("DELETE FROM drafts WHERE user_id=?", (user_id,))

    def history(self, user_id: int, limit: int = 10) -> list[tuple[Any, ...]]:
        with sqlite3.connect(self.path) as c:
            return c.execute(
                "SELECT id, total, status, created_at FROM requests "
                "WHERE user_id=? ORDER BY id DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()

    def set_status(self, request_id: int, status: str) -> None:
        with sqlite3.connect(self.path) as c:
            c.execute("UPDATE requests SET status=? WHERE id=?", (status, request_id))

    def manager_requests(self, status: str | None = None, limit: int = 20) -> list[tuple[Any, ...]]:
        limit = max(1, min(int(limit), 100))
        with sqlite3.connect(self.path) as c:
            if status:
                return c.execute(
                    "SELECT id, user_id, name, phone, total, status, address, created_at "
                    "FROM requests WHERE status=? ORDER BY id DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            return c.execute(
                "SELECT id, user_id, name, phone, total, status, address, created_at "
                "FROM requests ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()

    def get_request(self, request_id: int) -> tuple[Any, ...] | None:
        with sqlite3.connect(self.path) as c:
            return c.execute(
                "SELECT id, user_id, name, phone, config, total, status, address, created_at "
                "FROM requests WHERE id=?",
                (request_id,),
            ).fetchone()
