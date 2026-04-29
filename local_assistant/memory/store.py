from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MemoryStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        with self._lock, self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS profile (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tags TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS conversation_turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def seed_profile(self, values: dict[str, str]) -> None:
        for key, value in values.items():
            if self.get_profile().get(key) is None:
                self.set_profile(key, value)

    def get_profile(self) -> dict[str, str]:
        with self._lock, self._connect() as db:
            rows = db.execute("SELECT key, value FROM profile ORDER BY key").fetchall()
        return {row["key"]: row["value"] for row in rows}

    def set_profile(self, key: str, value: str) -> dict[str, str]:
        now = _now()
        with self._lock, self._connect() as db:
            db.execute(
                """
                INSERT INTO profile(key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                """,
                (key, value, now),
            )
        return {"key": key, "value": value, "updated_at": now}

    def add_memory(self, kind: str, content: str, tags: list[str] | None = None) -> dict[str, Any]:
        now = _now()
        with self._lock, self._connect() as db:
            cursor = db.execute(
                """
                INSERT INTO memories(kind, content, tags, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (kind, content, json.dumps(tags or []), now, now),
            )
            memory_id = int(cursor.lastrowid)
        return {
            "id": memory_id,
            "kind": kind,
            "content": content,
            "tags": tags or [],
            "created_at": now,
            "updated_at": now,
        }

    def list_memories(self, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock, self._connect() as db:
            rows = db.execute(
                "SELECT * FROM memories ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._memory_row(row) for row in rows]

    def search_memories(self, query: str, limit: int = 6) -> list[dict[str, Any]]:
        if not query.strip():
            return self.list_memories(limit=limit)
        needle = f"%{query.strip()}%"
        with self._lock, self._connect() as db:
            rows = db.execute(
                """
                SELECT * FROM memories
                WHERE content LIKE ? OR tags LIKE ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (needle, needle, limit),
            ).fetchall()
        return [self._memory_row(row) for row in rows]

    def delete_memory(self, memory_id: int) -> bool:
        with self._lock, self._connect() as db:
            cursor = db.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            return cursor.rowcount > 0

    def add_turn(self, role: str, content: str) -> dict[str, Any]:
        now = _now()
        with self._lock, self._connect() as db:
            cursor = db.execute(
                "INSERT INTO conversation_turns(role, content, created_at) VALUES (?, ?, ?)",
                (role, content, now),
            )
            turn_id = int(cursor.lastrowid)
        return {"id": turn_id, "role": role, "content": content, "created_at": now}

    def recent_turns(self, limit: int = 12) -> list[dict[str, Any]]:
        with self._lock, self._connect() as db:
            rows = db.execute(
                """
                SELECT * FROM conversation_turns
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {"id": row["id"], "role": row["role"], "content": row["content"], "created_at": row["created_at"]}
            for row in reversed(rows)
        ]

    def _memory_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "kind": row["kind"],
            "content": row["content"],
            "tags": json.loads(row["tags"] or "[]"),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
