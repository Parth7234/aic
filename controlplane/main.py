"""
ControlPlane.ai — Entry Point

Starts the FastAPI server with:
  - /v1/chat/completions  → AI proxy endpoint
  - /api/*                → Dashboard REST API + SSE
  - /dashboard            → Live monitoring dashboard
"""

from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from . import config, database
from .api import router as api_router
from .proxy import handle_chat_completion

# ── App Setup ────────────────────────────────────────────────────────────────

app = FastAPI(
    title="ControlPlane.ai",
    description="Real-time AI Observability & Guardrails",
    version="0.1.0",
)

# Mount dashboard static files
DASHBOARD_DIR = Path(__file__).parent / "dashboard"
app.mount("/dashboard", StaticFiles(directory=str(DASHBOARD_DIR)), name="dashboard")

# Register API routes
app.include_router(api_router)


# ── Startup ──────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    database.init_db()
    config.reload_policy_cache()
    mode = config.MODE.upper()
    print(f"\n{'=' * 60}")
    print(f"  ControlPlane Proxy starting on {config.HOST}:{config.PORT}")
    print(f"{'=' * 60}\n")
    print(f"  Dashboard: http://localhost:{config.PORT}/")
    print(f"  Proxy:     http://localhost:{config.PORT}/v1/chat/completions")
    print(f"  API:       http://localhost:{config.PORT}/api/stats")
    print(f"{'=' * 60}\n")


# ── Dashboard Route ──────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Serve the dashboard (no-cache to ensure fresh JS/CSS references)."""
    index_path = DASHBOARD_DIR / "index.html"
    return FileResponse(
        str(index_path),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


# ── Proxy Endpoint ───────────────────────────────────────────────────────────

@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """OpenAI-compatible chat completions endpoint with ControlPlane checks."""
    body = await request.json()
    result = await handle_chat_completion(body, headers=dict(request.headers))
    return result


# ── Run ──────────────────────────────────────────────────────────────────────

def main():
    uvicorn.run(
        "aic.controlplane.main:app",
        host=config.HOST,
        port=config.PORT,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
