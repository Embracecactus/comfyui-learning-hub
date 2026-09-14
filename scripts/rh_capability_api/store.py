"""任务库：SQLite 单文件，任务跨进程/重启可查。"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
  task_id      TEXT PRIMARY KEY,          -- 能力单元任务 ID（cap- 前缀）
  capability   TEXT NOT NULL,
  status       TEXT NOT NULL,             -- PENDING/RUNNING/SUCCEEDED/FAILED
  request      TEXT NOT NULL,
  rh_task_id   TEXT,
  outputs      TEXT,
  usage        TEXT,
  error        TEXT,
  created_at   REAL NOT NULL,
  updated_at   REAL NOT NULL
);
"""


class TaskStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._conn() as c:
            c.executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def create(self, capability: str, request: dict) -> str:
        task_id = "cap-" + uuid.uuid4().hex[:16]
        now = time.time()
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO tasks (task_id, capability, status, request, created_at, updated_at) "
                "VALUES (?, ?, 'PENDING', ?, ?, ?)",
                (task_id, capability, json.dumps(request, ensure_ascii=False), now, now))
        return task_id

    def update(self, task_id: str, **fields):
        fields["updated_at"] = time.time()
        cols = ", ".join(f"{k} = ?" for k in fields)
        with self._lock, self._conn() as c:
            c.execute(f"UPDATE tasks SET {cols} WHERE task_id = ?", (*fields.values(), task_id))

    def get(self, task_id: str) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        return self._row(row) if row else None

    def pending_with_rh_id(self) -> list[dict]:
        """PENDING/RUNNING 且已有 rh_task_id 的任务（供轮询线程续查）。"""
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM tasks WHERE status IN ('PENDING','RUNNING') AND rh_task_id IS NOT NULL"
            ).fetchall()
        return [self._row(r) for r in rows]

    @staticmethod
    def _row(row) -> dict:
        d = dict(row)
        for key in ("request", "outputs", "usage", "error"):
            if d.get(key):
                d[key] = json.loads(d[key])
        return d
