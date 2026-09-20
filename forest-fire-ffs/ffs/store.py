"""SQLite 持久化：事件、任务、核查反馈。"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from .models import FireEvent, Ranger, VerificationTask

# 核查结论 → 事件状态
FEEDBACK_TO_EVENT_STATUS = {
    "confirmed": "确认火情",
    "false_alarm": "误报",
    "need_backup": "需增援",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    event_id      TEXT PRIMARY KEY,
    lat           REAL NOT NULL,
    lon           REAL NOT NULL,
    uncertainty_m REAL NOT NULL,
    confidence    REAL NOT NULL,
    frp_max_mw    REAL NOT NULL,
    priority      TEXT NOT NULL,
    status        TEXT NOT NULL,
    first_detected TEXT NOT NULL,
    last_detected  TEXT NOT NULL,
    sources       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    task_id    TEXT PRIMARY KEY,
    event_id   TEXT NOT NULL REFERENCES events(event_id),
    ranger_id  TEXT NOT NULL,
    priority   TEXT NOT NULL,
    issued_at  TEXT NOT NULL,
    deadline   TEXT NOT NULL,
    distance_m REAL NOT NULL,
    eta_min    REAL NOT NULL,
    checklist  TEXT NOT NULL,
    status     TEXT NOT NULL,
    result     TEXT,
    note       TEXT,
    completed_at TEXT
);
"""


class Store:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)

    def close(self) -> None:
        self.conn.close()

    # ---- 写入 -------------------------------------------------------------
    def save_events(self, events: list[FireEvent]) -> None:
        self.conn.executemany(
            """INSERT OR REPLACE INTO events
               (event_id, lat, lon, uncertainty_m, confidence, frp_max_mw,
                priority, status, first_detected, last_detected, sources)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            [
                (e.event_id, e.lat, e.lon, e.uncertainty_m, e.confidence, e.frp_max_mw,
                 e.priority, e.status, e.first_detected.isoformat(), e.last_detected.isoformat(),
                 json.dumps(e.sources, ensure_ascii=False))
                for e in events
            ],
        )
        self.conn.commit()

    def save_tasks(self, tasks: list[VerificationTask]) -> None:
        self.conn.executemany(
            """INSERT OR REPLACE INTO tasks
               (task_id, event_id, ranger_id, priority, issued_at, deadline,
                distance_m, eta_min, checklist, status)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            [
                (t.task_id, t.event_id, t.ranger_id, t.priority,
                 t.issued_at.isoformat(), t.deadline.isoformat(), t.distance_m, t.eta_min,
                 json.dumps([vars(i) for i in t.checklist], ensure_ascii=False), t.status)
                for t in tasks
            ],
        )
        self.conn.commit()

    # ---- 核查反馈 ----------------------------------------------------------
    def record_feedback(self, task_id: str, result: str, note: str, completed_at: datetime) -> dict:
        """护林员回传核查结论，联动更新任务与事件状态。"""
        if result not in FEEDBACK_TO_EVENT_STATUS:
            raise ValueError(f"未知结论类型：{result}，应为 {sorted(FEEDBACK_TO_EVENT_STATUS)}")
        row = self.conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(f"任务不存在：{task_id}")
        self.conn.execute(
            "UPDATE tasks SET status='已完成', result=?, note=?, completed_at=? WHERE task_id=?",
            (result, note, completed_at.isoformat(), task_id),
        )
        self.conn.execute(
            "UPDATE events SET status=? WHERE event_id=?",
            (FEEDBACK_TO_EVENT_STATUS[result], row["event_id"]),
        )
        self.conn.commit()
        return {"task_id": task_id, "event_id": row["event_id"],
                "event_status": FEEDBACK_TO_EVENT_STATUS[result]}

    # ---- 查询 --------------------------------------------------------------
    def list_events(self) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM events ORDER BY event_id").fetchall()
        return [dict(r) for r in rows]

    def list_tasks(self) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM tasks ORDER BY task_id").fetchall()
        return [dict(r) for r in rows]
