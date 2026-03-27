"""Cache local em SQLite com TTL configurável."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional


class CacheManager:
    def __init__(self, db_path: Optional[Path] = None, ttl_seconds: int = 3600) -> None:
        if db_path is None:
            cache_dir = Path(os.getenv("CACHE_DIR", "data"))
            cache_dir.mkdir(parents=True, exist_ok=True)
            db_path = cache_dir / "cache.db"

        self.db_path = db_path
        self.ttl = timedelta(seconds=int(os.getenv("CACHE_TTL_SECONDS", ttl_seconds)))
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS responses (
                    key        TEXT PRIMARY KEY,
                    payload    TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

    @staticmethod
    def _make_key(url: str, params: dict | None = None) -> str:
        raw = url + json.dumps(params or {}, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(self, url: str, params: dict | None = None) -> Optional[Any]:
        key = self._make_key(url, params)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload, created_at FROM responses WHERE key = ?", (key,)
            ).fetchone()

        if row is None:
            return None

        created_at = datetime.fromisoformat(row["created_at"])
        if datetime.now() - created_at > self.ttl:
            self._delete(key)
            return None

        return json.loads(row["payload"])

    def set(self, url: str, data: Any, params: dict | None = None) -> None:
        key = self._make_key(url, params)
        payload = json.dumps(data, ensure_ascii=False)
        now = datetime.now().isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO responses (key, payload, created_at) VALUES (?, ?, ?)",
                (key, payload, now),
            )

    def _delete(self, key: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM responses WHERE key = ?", (key,))

    def clear(self) -> int:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM responses")
            return cur.rowcount

    def stats(self) -> dict:
        with self._connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM responses").fetchone()[0]
        size_bytes = self.db_path.stat().st_size if self.db_path.exists() else 0
        return {
            "entradas": count,
            "tamanho": f"{size_bytes / 1024:.1f} KB",
            "ttl": f"{int(self.ttl.total_seconds())}s",
            "arquivo": str(self.db_path),
        }
