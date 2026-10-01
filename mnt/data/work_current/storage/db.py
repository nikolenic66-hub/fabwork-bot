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
        with sqlite3.connect(self.path) as c:
            cur = c.execute(
                "INSERT INTO requests(user_id,name,phone,config,total,status,address,dedupe_key) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (user_id, name, phone, config, total, status, address, dedupe_key),
            )
            return int(cur.lastrowid)

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

    def get_request(self, request_id: int) -> tuple[Any, ...] | None:
        with sqlite3.connect(self.path) as c:
            return c.execute(
                "SELECT id, user_id, name, phone, config, total, status, address, created_at "
                "FROM requests WHERE id=?",
                (request_id,),
            ).fetchone()
