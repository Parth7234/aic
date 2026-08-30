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
                app_id TEXT DEFAULT 'default',
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

            CREATE TABLE IF NOT EXISTS policies (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                region TEXT DEFAULT 'global',
                risk_tolerance TEXT DEFAULT 'medium',
                policy_matrix TEXT NOT NULL,
                enabled_checks TEXT DEFAULT '[]',
                thresholds TEXT DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                created_by TEXT DEFAULT 'system',
                is_active INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS audit_log (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,
                request_id TEXT,
                policy_id TEXT,
                details TEXT DEFAULT '{}',
                actor TEXT DEFAULT 'system'
            );

            CREATE INDEX IF NOT EXISTS idx_requests_timestamp
                ON requests(timestamp DESC);
            CREATE INDEX IF NOT EXISTS idx_requests_risk
                ON requests(overall_risk);
            CREATE INDEX IF NOT EXISTS idx_requests_app_id
                ON requests(app_id);
            CREATE INDEX IF NOT EXISTS idx_check_results_request
                ON check_results(request_id);
            CREATE INDEX IF NOT EXISTS idx_check_results_dimension
                ON check_results(dimension);
            CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp
                ON audit_log(timestamp DESC);
        """)
    
    seed_default_policies()


def seed_default_policies():
    """Seed the database with default policies if empty."""
    with get_db() as conn:
        count = conn.execute("SELECT COUNT(*) as c FROM policies").fetchone()["c"]
        if count == 0:
            for policy_id, policy_data in config.DEFAULT_POLICY_PROFILES.items():
                now = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    """INSERT INTO policies
                       (id, name, description, region, risk_tolerance, policy_matrix,
                        enabled_checks, thresholds, created_at, updated_at, created_by, is_active)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        policy_id,
                        policy_data["name"],
                        policy_data.get("description", ""),
                        policy_data.get("region", "global"),
                        policy_data.get("risk_tolerance", "medium"),
                        json.dumps(policy_data["policy_matrix"]),
                        json.dumps(policy_data.get("enabled_checks", [])),
                        json.dumps(policy_data.get("thresholds", {})),
                        now,
                        now,
                        "system",
                        1
                    )
                )


# ── Request CRUD ─────────────────────────────────────────────────────────────

def insert_request(data: dict) -> str:
    """Insert a new request record. Returns the request ID."""
    with get_db() as conn:
        conn.execute(
            """INSERT INTO requests
               (id, app_id, timestamp, model, prompt, response, input_tokens, output_tokens,
                cost_usd, latency_ms, overall_risk, action_taken, edited_response, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                data["id"],
                data.get("app_id", "default"),
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
    app_id_filter: str | None = None,
) -> list[dict]:
    """Get paginated requests, optionally filtered."""
    query = "SELECT * FROM requests WHERE 1=1"
    params: list[Any] = []

    if risk_filter:
        query += " AND overall_risk = ?"
        params.append(risk_filter)
        
    if app_id_filter:
        query += " AND app_id = ?"
        params.append(app_id_filter)

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

def get_stats(app_id_filter: str | None = None) -> dict:
    """Get aggregate statistics for the dashboard."""
    with get_db() as conn:
        where_clause = "WHERE app_id = ?" if app_id_filter else ""
        params = (app_id_filter,) if app_id_filter else ()
        
        total_query = f"SELECT COUNT(*) as c FROM requests {where_clause}"
        total = conn.execute(total_query, params).fetchone()["c"]

        risk_dist = {}
        for row in conn.execute(
            f"SELECT overall_risk, COUNT(*) as c FROM requests {where_clause} GROUP BY overall_risk", params
        ):
            risk_dist[row["overall_risk"]] = row["c"]

        action_dist = {}
        for row in conn.execute(
            f"SELECT action_taken, COUNT(*) as c FROM requests {where_clause} GROUP BY action_taken", params
        ):
            action_dist[row["action_taken"]] = row["c"]
            
        app_dist = {}
        if not app_id_filter:
            for row in conn.execute(
                "SELECT app_id, COUNT(*) as c FROM requests GROUP BY app_id"
            ):
                app_dist[row["app_id"]] = row["c"]

        dim_risk = {}
        
        dim_risk_query = """
            SELECT cr.dimension, cr.risk_level, COUNT(*) as c
            FROM check_results cr
            JOIN requests r ON cr.request_id = r.id
        """
        if app_id_filter:
            dim_risk_query += " WHERE r.app_id = ?"
            
        dim_risk_query += " GROUP BY cr.dimension, cr.risk_level"

        for row in conn.execute(dim_risk_query, params):
            dim = row["dimension"]
            if dim not in dim_risk:
                dim_risk[dim] = {}
            dim_risk[dim][row["risk_level"]] = row["c"]

        cost_row = conn.execute(
            f"SELECT COALESCE(SUM(cost_usd), 0) as total, COALESCE(AVG(cost_usd), 0) as avg FROM requests {where_clause}", params
        ).fetchone()

        avg_latency = conn.execute(
            f"SELECT COALESCE(AVG(latency_ms), 0) as avg FROM requests {where_clause}", params
        ).fetchone()["avg"]

        # Recent cost trend (last 20 requests)
        cost_trend = []
        for row in conn.execute(
            f"SELECT timestamp, cost_usd FROM requests {where_clause} ORDER BY timestamp DESC LIMIT 20", params
        ):
            cost_trend.append({"timestamp": row["timestamp"], "cost": row["cost_usd"]})
        cost_trend.reverse()

        # Top flagged check categories
        top_flags = []
        top_flags_query = """
            SELECT cr.check_name, cr.dimension, COUNT(*) as c
            FROM check_results cr
            JOIN requests r ON cr.request_id = r.id
            WHERE cr.risk_level IN ('medium', 'high')
        """
        if app_id_filter:
            top_flags_query += " AND r.app_id = ?"
        top_flags_query += " GROUP BY cr.check_name ORDER BY c DESC LIMIT 10"
        
        for row in conn.execute(top_flags_query, params):
            top_flags.append({
                "check_name": row["check_name"],
                "dimension": row["dimension"],
                "count": row["c"],
            })

        return {
            "total_requests": total,
            "risk_distribution": risk_dist,
            "action_distribution": action_dist,
            "app_distribution": app_dist,
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


# ── Policies CRUD ────────────────────────────────────────────────────────────

def get_all_policies() -> list[dict]:
    """Get all active policies."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM policies WHERE is_active = 1"
        ).fetchall()
        
        policies = []
        for r in rows:
            p = dict(r)
            p["policy_matrix"] = json.loads(p["policy_matrix"])
            p["enabled_checks"] = json.loads(p["enabled_checks"])
            p["thresholds"] = json.loads(p["thresholds"])
            policies.append(p)
        return policies


def get_policy(policy_id: str) -> dict | None:
    """Get a single active policy."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM policies WHERE id = ? AND is_active = 1", (policy_id,)
        ).fetchone()
        
        if not row:
            return None
            
        p = dict(row)
        p["policy_matrix"] = json.loads(p["policy_matrix"])
        p["enabled_checks"] = json.loads(p["enabled_checks"])
        p["thresholds"] = json.loads(p["thresholds"])
        return p


def upsert_policy(data: dict) -> str:
    """Insert or update a policy."""
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        # Check if exists
        existing = conn.execute("SELECT id FROM policies WHERE id = ?", (data["id"],)).fetchone()
        
        if existing:
            conn.execute(
                """UPDATE policies SET 
                   name = ?, description = ?, region = ?, risk_tolerance = ?,
                   policy_matrix = ?, enabled_checks = ?, thresholds = ?,
                   updated_at = ?, is_active = ?
                   WHERE id = ?""",
                (
                    data["name"],
                    data.get("description", ""),
                    data.get("region", "global"),
                    data.get("risk_tolerance", "medium"),
                    json.dumps(data["policy_matrix"]),
                    json.dumps(data.get("enabled_checks", [])),
                    json.dumps(data.get("thresholds", {})),
                    now,
                    data.get("is_active", 1),
                    data["id"]
                )
            )
        else:
            conn.execute(
                """INSERT INTO policies
                   (id, name, description, region, risk_tolerance, policy_matrix,
                    enabled_checks, thresholds, created_at, updated_at, created_by, is_active)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    data["id"],
                    data["name"],
                    data.get("description", ""),
                    data.get("region", "global"),
                    data.get("risk_tolerance", "medium"),
                    json.dumps(data["policy_matrix"]),
                    json.dumps(data.get("enabled_checks", [])),
                    json.dumps(data.get("thresholds", {})),
                    now,
                    now,
                    data.get("created_by", "system"),
                    data.get("is_active", 1)
                )
            )
    return data["id"]


def delete_policy(policy_id: str):
    """Soft delete a policy."""
    with get_db() as conn:
        conn.execute("UPDATE policies SET is_active = 0, updated_at = ? WHERE id = ?", 
                    (datetime.now(timezone.utc).isoformat(), policy_id))


# ── Audit Log ────────────────────────────────────────────────────────────────

def insert_audit_log(data: dict) -> str:
    """Insert an audit log entry."""
    if "id" not in data:
        import uuid
        data["id"] = str(uuid.uuid4())
        
    with get_db() as conn:
        conn.execute(
            """INSERT INTO audit_log
               (id, timestamp, event_type, request_id, policy_id, details, actor)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                data["id"],
                data.get("timestamp", datetime.now(timezone.utc).isoformat()),
                data["event_type"],
                data.get("request_id"),
                data.get("policy_id"),
                json.dumps(data.get("details", {})),
                data.get("actor", "system")
            )
        )
    return data["id"]


def get_audit_log(policy_id: str | None = None, event_type: str | None = None, limit: int = 50) -> list[dict]:
    """Get audit log entries, optionally filtered."""
    query = "SELECT * FROM audit_log WHERE 1=1"
    params = []
    
    if policy_id:
        query += " AND policy_id = ?"
        params.append(policy_id)
        
    if event_type:
        query += " AND event_type = ?"
        params.append(event_type)
        
    query += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)
    
    with get_db() as conn:
        rows = conn.execute(query, params).fetchall()
        logs = []
        for r in rows:
            log = dict(r)
            log["details"] = json.loads(log["details"])
            logs.append(log)
        return logs
