import json
import os
import sqlite3
import threading
from typing import List, Optional, Dict, Any

DB_PATH = os.path.expanduser("~/.config/bcper/bcper.db")
_db_lock = threading.Lock()


def _ensure_dir():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)


def _get_conn() -> sqlite3.Connection:
    _ensure_dir()
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str = None) -> None:
    path = db_path or DB_PATH
    _ensure_dir()
    with _db_lock:
        conn = sqlite3.connect(path)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id            TEXT PRIMARY KEY,
                job_id        TEXT,
                job_name      TEXT NOT NULL,
                target_type   TEXT NOT NULL,
                target_name   TEXT NOT NULL,
                store_name    TEXT NOT NULL,
                store_path    TEXT NOT NULL,
                archive_name  TEXT NOT NULL,
                started_at    TEXT NOT NULL,
                completed_at  TEXT,
                status        TEXT NOT NULL,
                hash          TEXT,
                encrypted     INTEGER NOT NULL DEFAULT 0,
                meta_json     TEXT,
                error_message TEXT
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_job ON runs(job_id, store_name)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_store ON runs(store_name)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_started ON runs(started_at)")
        conn.commit()
        conn.close()


def insert_run(record: Dict[str, Any]) -> str:
    with _db_lock:
        conn = _get_conn()
        conn.execute(
            """
            INSERT INTO runs (
                id, job_id, job_name, target_type, target_name,
                store_name, store_path, archive_name, started_at,
                completed_at, status, hash, encrypted, meta_json, error_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["id"],
                record.get("job_id"),
                record["job_name"],
                record["target_type"],
                record["target_name"],
                record["store_name"],
                record["store_path"],
                record["archive_name"],
                record["started_at"],
                record.get("completed_at"),
                record["status"],
                record.get("hash"),
                1 if record.get("encrypted") else 0,
                record.get("meta_json"),
                record.get("error_message"),
            ),
        )
        conn.commit()
        conn.close()
    return record["id"]


def update_run(run_id: str, **kwargs) -> None:
    allowed = {
        "completed_at", "status", "hash", "encrypted",
        "meta_json", "error_message", "archive_name",
    }
    cols = [k for k in kwargs if k in allowed]
    if not cols:
        return
    values = []
    for c in cols:
        v = kwargs[c]
        if c == "encrypted":
            v = 1 if v else 0
        values.append(v)
    values.append(run_id)
    with _db_lock:
        conn = _get_conn()
        conn.execute(
            f"UPDATE runs SET {', '.join(f'{c}=?' for c in cols)} WHERE id=?",
            values,
        )
        conn.commit()
        conn.close()


def get_run(run_id: str) -> Optional[Dict[str, Any]]:
    with _db_lock:
        conn = _get_conn()
        row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        conn.close()
    return dict(row) if row else None


def list_runs(
    job_id: str = None,
    store_name: str = None,
    status: str = None,
    limit: int = None,
) -> List[Dict[str, Any]]:
    clauses = []
    params = []
    if job_id is not None:
        clauses.append("job_id = ?")
        params.append(job_id)
    if store_name is not None:
        clauses.append("store_name = ?")
        params.append(store_name)
    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    sql = "SELECT * FROM runs"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY started_at DESC"
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    with _db_lock:
        conn = _get_conn()
        rows = conn.execute(sql, params).fetchall()
        conn.close()
    return [dict(r) for r in rows]


def list_runs_for_retention(job_id: str, store_name: str, keep_last: int) -> List[Dict[str, Any]]:
    """Return runs to delete (everything beyond the N most recent successes)."""
    with _db_lock:
        conn = _get_conn()
        rows = conn.execute(
            """
            SELECT * FROM runs
            WHERE job_id = ? AND store_name = ? AND status = 'success'
            ORDER BY started_at DESC
            """,
            (job_id, store_name),
        ).fetchall()
        conn.close()
    all_runs = [dict(r) for r in rows]
    if len(all_runs) <= keep_last:
        return []
    return all_runs[keep_last:]


def delete_run(run_id: str) -> Optional[Dict[str, Any]]:
    with _db_lock:
        conn = _get_conn()
        row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row:
            conn.execute("DELETE FROM runs WHERE id=?", (run_id,))
            conn.commit()
        conn.close()
    return dict(row) if row else None


def delete_runs(run_ids: List[str]) -> int:
    if not run_ids:
        return 0
    placeholders = ",".join("?" * len(run_ids))
    with _db_lock:
        conn = _get_conn()
        cur = conn.execute(f"DELETE FROM runs WHERE id IN ({placeholders})", tuple(run_ids))
        conn.commit()
        conn.close()
    return cur.rowcount
