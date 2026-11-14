"""
Persistent job registry — SQLite with WAL.

Chosen because the control plane is a small instance with a persistent EBS disk
and the spec allows "SQLite with WAL on persistent EBS for the initial
lightweight job registry". No extra service (Redis/Postgres) is required.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from typing import Iterable, Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id         TEXT PRIMARY KEY,
  user_id    TEXT NOT NULL,
  type       TEXT NOT NULL,
  state      TEXT NOT NULL,
  model      TEXT,
  params     TEXT NOT NULL DEFAULT '{}',
  idem_key   TEXT,
  created    REAL NOT NULL,
  updated    REAL NOT NULL,
  deadline   REAL,
  result_url TEXT,
  error      TEXT,
  gpu_seconds REAL DEFAULT 0,
  provider   TEXT,
  attempts   INTEGER DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS jobs_idem ON jobs(user_id, idem_key)
  WHERE idem_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS jobs_user_created ON jobs(user_id, created DESC);
CREATE INDEX IF NOT EXISTS jobs_state ON jobs(state);

CREATE TABLE IF NOT EXISTS gpu_usage (
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  ts       REAL NOT NULL,
  event    TEXT NOT NULL,        -- start | stop | session
  seconds  REAL DEFAULT 0,
  instance TEXT
);

CREATE TABLE IF NOT EXISTS loras (
  id         TEXT PRIMARY KEY,
  user_id    TEXT,              -- NULL = built-in
  name       TEXT NOT NULL,
  base       TEXT,
  trigger    TEXT,
  weight     REAL DEFAULT 0.8,
  license    TEXT,
  source_url TEXT,
  checksum   TEXT,
  size       INTEGER DEFAULT 0,
  active     INTEGER DEFAULT 1,
  created    REAL NOT NULL
);
"""


class JobStore:
    def __init__(self, path: str, clock=time.time):
        self.clock = clock
        d = os.path.dirname(os.path.abspath(path))
        if d:
            os.makedirs(d, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.executescript(_SCHEMA)
        self._db.commit()

    # ---- jobs -----------------------------------------------------------
    def create_job(self, user_id: str, job_type: str, model: str, params: dict,
                   idem_key: Optional[str] = None, deadline_seconds: Optional[int] = None) -> dict:
        now = self.clock()
        with self._lock:
            if idem_key:
                row = self._db.execute(
                    "SELECT * FROM jobs WHERE user_id=? AND idem_key=?", (user_id, idem_key)).fetchone()
                if row:
                    return dict(row)  # idempotent replay
            jid = uuid.uuid4().hex
            self._db.execute(
                "INSERT INTO jobs(id,user_id,type,state,model,params,idem_key,created,updated,deadline)"
                " VALUES(?,?,?,?,?,?,?,?,?,?)",
                (jid, user_id, job_type, "created", model, json.dumps(params),
                 idem_key, now, now,
                 now + deadline_seconds if deadline_seconds else None))
            self._db.commit()
        return self.get_job(jid)

    def get_job(self, job_id: str) -> Optional[dict]:
        row = self._db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return dict(row) if row else None

    def list_jobs(self, user_id: str, limit: int = 50) -> list:
        rows = self._db.execute(
            "SELECT * FROM jobs WHERE user_id=? ORDER BY created DESC LIMIT ?",
            (user_id, limit)).fetchall()
        return [dict(r) for r in rows]

    def set_state(self, job_id: str, state: str, **fields) -> None:
        sets = ["state=?", "updated=?"]
        vals = [state, self.clock()]
        for k in ("result_url", "error", "provider", "gpu_seconds", "model"):
            if k in fields and fields[k] is not None:
                sets.append(f"{k}=?"); vals.append(fields[k])
        if fields.get("bump_attempts"):
            sets.append("attempts=attempts+1")
        vals.append(job_id)
        with self._lock:
            self._db.execute(f"UPDATE jobs SET {','.join(sets)} WHERE id=?", vals)
            self._db.commit()

    def next_queued(self) -> Optional[dict]:
        row = self._db.execute(
            "SELECT * FROM jobs WHERE state IN"
            " ('created','queued','waking_gpu','booting','loading_model')"
            " ORDER BY created ASC LIMIT 1").fetchone()
        return dict(row) if row else None

    def count_by_state(self, states: Iterable[str]) -> int:
        qs = ",".join("?" * len(list(states)))
        row = self._db.execute(f"SELECT COUNT(*) c FROM jobs WHERE state IN ({qs})",
                               tuple(states)).fetchone()
        return int(row["c"])

    def count_user_day(self, user_id: str, job_type: str) -> int:
        start = self.clock() - (self.clock() % 86400)
        row = self._db.execute(
            "SELECT COUNT(*) c FROM jobs WHERE user_id=? AND type=? AND created>=?",
            (user_id, job_type, start)).fetchone()
        return int(row["c"])

    def count_user_pending(self, user_id: str) -> int:
        row = self._db.execute(
            "SELECT COUNT(*) c FROM jobs WHERE user_id=? AND state NOT IN"
            " ('succeeded','failed','cancelled','timed_out')", (user_id,)).fetchone()
        return int(row["c"])

    def running_count(self) -> int:
        return self.count_by_state(["running", "saving_result"])

    # ---- gpu usage ------------------------------------------------------
    def add_gpu_event(self, event: str, seconds: float = 0.0, instance: str = "") -> None:
        with self._lock:
            self._db.execute("INSERT INTO gpu_usage(ts,event,seconds,instance) VALUES(?,?,?,?)",
                             (self.clock(), event, seconds, instance))
            self._db.commit()

    def gpu_seconds_since(self, since_ts: float) -> float:
        row = self._db.execute(
            "SELECT COALESCE(SUM(seconds),0) s FROM gpu_usage WHERE ts>=? AND event='session'",
            (since_ts,)).fetchone()
        return float(row["s"])

    # ---- loras ----------------------------------------------------------
    def add_lora(self, **kw) -> dict:
        lid = kw.get("id") or uuid.uuid4().hex
        with self._lock:
            self._db.execute(
                "INSERT INTO loras(id,user_id,name,base,trigger,weight,license,source_url,checksum,size,active,created)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (lid, kw.get("user_id"), kw.get("name", "untitled"), kw.get("base"),
                 kw.get("trigger"), kw.get("weight", 0.8), kw.get("license"),
                 kw.get("source_url"), kw.get("checksum"), kw.get("size", 0),
                 1 if kw.get("active", True) else 0, self.clock()))
            self._db.commit()
        return self.get_lora(lid)

    def get_lora(self, lid: str) -> Optional[dict]:
        row = self._db.execute("SELECT * FROM loras WHERE id=?", (lid,)).fetchone()
        return dict(row) if row else None

    def list_loras(self, user_id: Optional[str] = None) -> list:
        rows = self._db.execute(
            "SELECT * FROM loras WHERE user_id IS NULL OR user_id=? ORDER BY created DESC",
            (user_id,)).fetchall()
        return [dict(r) for r in rows]

    def delete_lora(self, lid: str, user_id: str) -> bool:
        with self._lock:
            cur = self._db.execute("DELETE FROM loras WHERE id=? AND user_id=?", (lid, user_id))
            self._db.commit()
        return cur.rowcount > 0

    def close(self) -> None:
        self._db.close()
