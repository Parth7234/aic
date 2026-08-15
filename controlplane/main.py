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
    mode = config.MODE.upper()
    print(f"\n{'═' * 60}")
    print(f"  ControlPlane.ai — Real-time AI Observability")
    print(f"  Mode: {mode}")
    print(f"  Dashboard: http://localhost:{config.PORT}/")
    print(f"  Proxy:     http://localhost:{config.PORT}/v1/chat/completions")
    print(f"  API:       http://localhost:{config.PORT}/api/stats")
    print(f"{'═' * 60}\n")


# ── Dashboard Route ──────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Serve the dashboard."""
    index_path = DASHBOARD_DIR / "index.html"
    return FileResponse(str(index_path))


# ── Proxy Endpoint ───────────────────────────────────────────────────────────

@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """OpenAI-compatible chat completions endpoint with ControlPlane checks."""
    body = await request.json()
    result = await handle_chat_completion(body)
    return result


# ── Run ──────────────────────────────────────────────────────────────────────

def main():
    uvicorn.run(
        "controlplane.main:app",
        host=config.HOST,
        port=config.PORT,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
