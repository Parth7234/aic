"""
ControlPlane API — REST endpoints and SSE stream for the dashboard.
"""

import asyncio
import json

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from . import database, proxy

router = APIRouter(prefix="/api")


# ── Requests ─────────────────────────────────────────────────────────────────

@router.get("/requests")
async def list_requests(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    risk: str | None = Query(None),
):
    """Get paginated list of requests."""
    requests = database.get_requests(limit=limit, offset=offset, risk_filter=risk)
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
async def get_stats():
    """Get aggregate statistics for the dashboard."""
    return database.get_stats()


# ── Human Review Actions ─────────────────────────────────────────────────────

@router.post("/requests/{request_id}/action")
async def take_action(request_id: str, request: Request):
    """Human review action — approve, block, or release a response."""
    body = await request.json()
    action = body.get("action", "approve")

    if action == "approve":
        database.update_request(request_id, {"action_taken": "pass"})
    elif action == "block":
        database.update_request(request_id, {"action_taken": "block"})
    elif action == "release":
        database.update_request(request_id, {"action_taken": "pass"})

    # Broadcast the action
    await proxy._broadcast_sse("human_action", {
        "request_id": request_id,
        "action": action,
    })

    return {"status": "ok", "action": action, "request_id": request_id}


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
