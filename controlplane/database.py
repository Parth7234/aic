"""
ControlPlane Database — SQLite storage for requests, check results, and metrics.
"""

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from . import config

_local = threading.local()


def _get_connection() -> sqlite3.Connection:
    """Get a thread-local SQLite connection."""
    if not hasattr(_local, "conn") or _local.conn is None:
        conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        _local.conn = conn
    return _local.conn


@contextmanager
def get_db():
    """Context manager for database operations."""
    conn = _get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def init_db():
    """Create tables if they don't exist."""
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS requests (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                model TEXT NOT NULL,
                prompt TEXT NOT NULL,
                response TEXT NOT NULL,
                input_tokens INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                cost_usd REAL DEFAULT 0.0,
                latency_ms REAL DEFAULT 0.0,
                overall_risk TEXT DEFAULT 'low',
                action_taken TEXT DEFAULT 'pass',
                edited_response TEXT,
                metadata TEXT DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS check_results (
                id TEXT PRIMARY KEY,
                request_id TEXT NOT NULL REFERENCES requests(id),
                dimension TEXT NOT NULL,
                check_name TEXT NOT NULL,
                score REAL DEFAULT 0.0,
                risk_level TEXT DEFAULT 'low',
                details TEXT DEFAULT '{}',
                is_sync INTEGER DEFAULT 0,
                timestamp TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_requests_timestamp
                ON requests(timestamp DESC);
            CREATE INDEX IF NOT EXISTS idx_requests_risk
                ON requests(overall_risk);
            CREATE INDEX IF NOT EXISTS idx_check_results_request
                ON check_results(request_id);
            CREATE INDEX IF NOT EXISTS idx_check_results_dimension
                ON check_results(dimension);
        """)


# ── Request CRUD ─────────────────────────────────────────────────────────────

def insert_request(data: dict) -> str:
    """Insert a new request record. Returns the request ID."""
    with get_db() as conn:
        conn.execute(
            """INSERT INTO requests
               (id, timestamp, model, prompt, response, input_tokens, output_tokens,
                cost_usd, latency_ms, overall_risk, action_taken, edited_response, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                data["id"],
                data.get("timestamp", datetime.now(timezone.utc).isoformat()),
                data.get("model", "unknown"),
                data.get("prompt", ""),
                data.get("response", ""),
                data.get("input_tokens", 0),
                data.get("output_tokens", 0),
                data.get("cost_usd", 0.0),
                data.get("latency_ms", 0.0),
                data.get("overall_risk", "low"),
                data.get("action_taken", "pass"),
                data.get("edited_response"),
                json.dumps(data.get("metadata", {})),
            ),
        )
    return data["id"]


def update_request(request_id: str, updates: dict):
    """Update fields on a request record."""
    allowed = {
        "overall_risk", "action_taken", "edited_response",
        "cost_usd", "latency_ms", "input_tokens", "output_tokens",
    }
    fields = {k: v for k, v in updates.items() if k in allowed}
    if not fields:
        return
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [request_id]
    with get_db() as conn:
        conn.execute(
            f"UPDATE requests SET {set_clause} WHERE id = ?", values
        )


def get_request(request_id: str) -> dict | None:
    """Get a single request with all its check results."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM requests WHERE id = ?", (request_id,)
        ).fetchone()
        if not row:
            return None
        req = dict(row)
        checks = conn.execute(
            "SELECT * FROM check_results WHERE request_id = ? ORDER BY timestamp",
            (request_id,),
        ).fetchall()
        req["checks"] = [dict(c) for c in checks]
        return req


def get_requests(
    limit: int = 50,
    offset: int = 0,
    risk_filter: str | None = None,
    dimension_filter: str | None = None,
) -> list[dict]:
    """Get paginated requests, optionally filtered."""
    query = "SELECT * FROM requests"
    params: list[Any] = []

    if risk_filter:
        query += " WHERE overall_risk = ?"
        params.append(risk_filter)

    query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    with get_db() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


# ── Check Results ────────────────────────────────────────────────────────────

def insert_check_result(data: dict) -> str:
    """Insert a check result."""
    with get_db() as conn:
        conn.execute(
            """INSERT INTO check_results
               (id, request_id, dimension, check_name, score,
                risk_level, details, is_sync, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                data["id"],
                data["request_id"],
                data["dimension"],
                data["check_name"],
                data.get("score", 0.0),
                data.get("risk_level", "low"),
                json.dumps(data.get("details", {})),
                1 if data.get("is_sync") else 0,
                data.get("timestamp", datetime.now(timezone.utc).isoformat()),
            ),
        )
    return data["id"]


# ── Aggregation / Stats ─────────────────────────────────────────────────────

def get_stats() -> dict:
    """Get aggregate statistics for the dashboard."""
    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) as c FROM requests").fetchone()["c"]

        risk_dist = {}
        for row in conn.execute(
            "SELECT overall_risk, COUNT(*) as c FROM requests GROUP BY overall_risk"
        ):
            risk_dist[row["overall_risk"]] = row["c"]

        action_dist = {}
        for row in conn.execute(
            "SELECT action_taken, COUNT(*) as c FROM requests GROUP BY action_taken"
        ):
            action_dist[row["action_taken"]] = row["c"]

        dim_risk = {}
        for row in conn.execute(
            """SELECT dimension, risk_level, COUNT(*) as c
               FROM check_results GROUP BY dimension, risk_level"""
        ):
            dim = row["dimension"]
            if dim not in dim_risk:
                dim_risk[dim] = {}
            dim_risk[dim][row["risk_level"]] = row["c"]

        cost_row = conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) as total, COALESCE(AVG(cost_usd), 0) as avg FROM requests"
        ).fetchone()

        avg_latency = conn.execute(
            "SELECT COALESCE(AVG(latency_ms), 0) as avg FROM requests"
        ).fetchone()["avg"]

        # Recent cost trend (last 20 requests)
        cost_trend = []
        for row in conn.execute(
            "SELECT timestamp, cost_usd FROM requests ORDER BY timestamp DESC LIMIT 20"
        ):
            cost_trend.append({"timestamp": row["timestamp"], "cost": row["cost_usd"]})
        cost_trend.reverse()

        # Top flagged check categories
        top_flags = []
        for row in conn.execute(
            """SELECT check_name, dimension, COUNT(*) as c
               FROM check_results WHERE risk_level IN ('medium', 'high')
               GROUP BY check_name ORDER BY c DESC LIMIT 10"""
        ):
            top_flags.append({
                "check_name": row["check_name"],
                "dimension": row["dimension"],
                "count": row["c"],
            })

        return {
            "total_requests": total,
            "risk_distribution": risk_dist,
            "action_distribution": action_dist,
            "dimension_risks": dim_risk,
            "total_cost_usd": round(cost_row["total"], 6),
            "avg_cost_usd": round(cost_row["avg"], 6),
            "avg_latency_ms": round(avg_latency, 2),
            "cost_trend": cost_trend,
            "top_flags": top_flags,
        }


def get_rolling_avg_cost(window: int = 20) -> float:
    """Get rolling average cost over the last N requests."""
    with get_db() as conn:
        row = conn.execute(
            """SELECT COALESCE(AVG(cost_usd), 0) as avg
               FROM (SELECT cost_usd FROM requests ORDER BY timestamp DESC LIMIT ?)""",
            (window,),
        ).fetchone()
        return row["avg"]
