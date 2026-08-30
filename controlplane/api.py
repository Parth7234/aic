"""
ControlPlane API — REST endpoints and SSE stream for the dashboard.
"""

import asyncio
import json

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from . import config, database, proxy

router = APIRouter(prefix="/api")


# ── Requests ─────────────────────────────────────────────────────────────────

@router.get("/requests")
async def list_requests(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    risk: str | None = Query(None),
    app: str | None = Query(None),
):
    """Get paginated list of requests."""
    requests = database.get_requests(limit=limit, offset=offset, risk_filter=risk, app_id_filter=app)
    return {"requests": requests, "limit": limit, "offset": offset}


@router.get("/requests/{request_id}")
async def get_request_detail(request_id: str):
    """Get full detail of a single request with all check results."""
    req = database.get_request(request_id)
    if not req:
        return {"error": "Request not found"}, 404
    return req


# ── Stats ────────────────────────────────────────────────────────────────────

@router.get("/stats")
async def get_stats(app: str | None = Query(None)):
    """Get aggregate statistics for the dashboard."""
    return database.get_stats(app_id_filter=app)


# ── Policies ─────────────────────────────────────────────────────────────────

@router.get("/policies")
async def get_policies():
    """Get available policy profiles."""
    return database.get_all_policies()


@router.get("/policies/{policy_id}")
async def get_policy(policy_id: str):
    """Get a single policy profile."""
    p = database.get_policy(policy_id)
    if not p:
        return {"error": "Policy not found"}, 404
    return p


@router.post("/policies")
async def create_policy(request: Request):
    """Create a new policy."""
    data = await request.json()
    if not data.get("id") or not data.get("name") or not data.get("policy_matrix"):
        return {"error": "Missing required fields (id, name, policy_matrix)"}, 400
        
    database.upsert_policy(data)
    config.update_cached_policy(data["id"], database.get_policy(data["id"]))
    
    database.insert_audit_log({
        "event_type": "policy_change",
        "policy_id": data["id"],
        "details": {"action": "create", "data": data},
        "actor": "admin"
    })
    return {"status": "ok", "id": data["id"]}


@router.put("/policies/{policy_id}")
async def update_policy(policy_id: str, request: Request):
    """Update an existing policy."""
    data = await request.json()
    data["id"] = policy_id
    
    database.upsert_policy(data)
    config.update_cached_policy(policy_id, database.get_policy(policy_id))
    
    database.insert_audit_log({
        "event_type": "policy_change",
        "policy_id": policy_id,
        "details": {"action": "update", "data": data},
        "actor": "admin"
    })
    return {"status": "ok", "id": policy_id}


@router.delete("/policies/{policy_id}")
async def delete_policy(policy_id: str):
    """Delete a policy."""
    database.delete_policy(policy_id)
    if policy_id in config.ACTIVE_POLICIES:
        del config.ACTIVE_POLICIES[policy_id]
        
    database.insert_audit_log({
        "event_type": "policy_change",
        "policy_id": policy_id,
        "details": {"action": "delete"},
        "actor": "admin"
    })
    return {"status": "ok"}


# ── Audit Log ────────────────────────────────────────────────────────────────

@router.get("/audit-log")
async def get_audit_log(
    policy_id: str | None = Query(None),
    event_type: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200)
):
    """Get audit log entries."""
    logs = database.get_audit_log(policy_id=policy_id, event_type=event_type, limit=limit)
    return {"logs": logs, "limit": limit}


# ── Human Review Actions ─────────────────────────────────────────────────────

@router.post("/requests/{request_id}/action")
async def take_action(request_id: str, request: Request):
    """Human review action — approve, block, or release a response."""
    body = await request.json()
    human_action = body.get("action", "approve")

    req = database.get_request(request_id)
    if not req:
        return {"error": "Request not found"}, 404

    original_action = req.get("action_taken", "pass")
    
    # Classify feedback type
    feedback_type = "confirmed"
    if original_action in ["block", "escalate", "flag"]:
        if human_action in ["approve", "release"]:
            feedback_type = "false_positive"
        elif human_action == "block":
            feedback_type = "confirmed"
    elif original_action == "edit":
        if human_action == "release":
            feedback_type = "false_positive"
        elif human_action == "approve":
            feedback_type = "confirmed"
    elif original_action == "pass":
        if human_action == "block":
            feedback_type = "false_negative"
        elif human_action == "approve":
            feedback_type = "confirmed"

    # Identify highest risk check to associate feedback
    check_name = None
    dimension = None
    if req.get("checks"):
        # Sort checks by risk_level (high > medium > low)
        risk_map = {"high": 3, "medium": 2, "low": 1}
        sorted_checks = sorted(req["checks"], key=lambda c: risk_map.get(c.get("risk_level", "low"), 0), reverse=True)
        check_name = sorted_checks[0].get("check_name")
        dimension = sorted_checks[0].get("dimension")

    # Update request action
    if human_action == "approve" or human_action == "release":
        database.update_request(request_id, {"action_taken": "pass"})
    elif human_action == "block":
        database.update_request(request_id, {"action_taken": "block"})

    # Insert feedback record
    database.insert_feedback({
        "request_id": request_id,
        "original_action": original_action,
        "human_action": human_action,
        "feedback_type": feedback_type,
        "check_name": check_name,
        "dimension": dimension,
        "reason": body.get("reason", "")
    })
    
    database.insert_audit_log({
        "event_type": "human_override",
        "request_id": request_id,
        "details": {"original_action": original_action, "human_action": human_action, "feedback_type": feedback_type},
        "actor": "admin"
    })

    # Broadcast the action and feedback update
    await proxy._broadcast_sse("human_action", {
        "request_id": request_id,
        "action": human_action,
    })
    await proxy._broadcast_sse("feedback_recorded", {
        "request_id": request_id
    })

    return {"status": "ok", "action": human_action, "feedback_type": feedback_type}

# ── Feedback ─────────────────────────────────────────────────────────────────

@router.get("/feedback/stats")
async def get_feedback_stats_api(app: str | None = Query(None)):
    """Get aggregated feedback metrics."""
    return database.get_feedback_stats(app_id_filter=app)

@router.get("/feedback")
async def get_recent_feedback_api(limit: int = Query(50, ge=1, le=200)):
    """Get recent human overrides."""
    return {"feedback": database.get_recent_feedback(limit=limit), "limit": limit}


# ── Server-Sent Events Stream ───────────────────────────────────────────────

@router.get("/stream")
async def sse_stream():
    """SSE endpoint for real-time dashboard updates."""
    queue = proxy.subscribe_sse()

    async def event_generator():
        try:
            # Send initial keepalive
            yield f"data: {json.dumps({'type': 'connected', 'data': {}})}\n\n"

            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {message}\n\n"
                except asyncio.TimeoutError:
                    # Send keepalive ping
                    yield f"data: {json.dumps({'type': 'ping', 'data': {}})}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            proxy.unsubscribe_sse(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
