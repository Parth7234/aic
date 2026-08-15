"""
ControlPlane Configuration — Central settings, thresholds, and policy rules.

All values can be overridden via environment variables or a .env file.
"""

import os
from dotenv import load_dotenv

load_dotenv()


# ── Mode ─────────────────────────────────────────────────────────────────────
# "mock" = simulated LLM responses (no API key needed)
# "live" = proxy to a real LLM provider
MODE = os.getenv("CONTROLPLANE_MODE", "mock")

# ── LLM Provider (only used in live mode) ────────────────────────────────────
LLM_API_KEY = os.getenv("OPENAI_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
LLM_DEFAULT_MODEL = os.getenv("LLM_DEFAULT_MODEL", "gpt-3.5-turbo")

# ── Server ───────────────────────────────────────────────────────────────────
HOST = os.getenv("CONTROLPLANE_HOST", "0.0.0.0")
PORT = int(os.getenv("CONTROLPLANE_PORT", "8000"))

# ── Database ─────────────────────────────────────────────────────────────────
DB_PATH = os.getenv("CONTROLPLANE_DB", "controlplane.db")

# ── Performance Thresholds ───────────────────────────────────────────────────
# Confidence score below this → flag as low confidence
CONFIDENCE_THRESHOLD_LOW = float(os.getenv("CONFIDENCE_THRESHOLD_LOW", "0.3"))
CONFIDENCE_THRESHOLD_MEDIUM = float(os.getenv("CONFIDENCE_THRESHOLD_MEDIUM", "0.6"))

# Self-consistency: semantic divergence threshold
CONSISTENCY_DIVERGENCE_THRESHOLD = float(
    os.getenv("CONSISTENCY_DIVERGENCE_THRESHOLD", "0.4")
)

# Hallucination score (0=faithful, 1=hallucinated)
HALLUCINATION_THRESHOLD_MEDIUM = float(
    os.getenv("HALLUCINATION_THRESHOLD_MEDIUM", "0.4")
)
HALLUCINATION_THRESHOLD_HIGH = float(
    os.getenv("HALLUCINATION_THRESHOLD_HIGH", "0.7")
)

# ── Cost Thresholds ──────────────────────────────────────────────────────────
# Per-request token budget (input + output)
TOKEN_BUDGET_PER_REQUEST = int(os.getenv("TOKEN_BUDGET_PER_REQUEST", "4096"))

# Per-request cost budget (USD)
COST_BUDGET_PER_REQUEST = float(os.getenv("COST_BUDGET_PER_REQUEST", "0.10"))

# Anomaly detection: flag if cost exceeds rolling_avg * this multiplier
COST_ANOMALY_MULTIPLIER = float(os.getenv("COST_ANOMALY_MULTIPLIER", "3.0"))

# ── Responsibility Thresholds ────────────────────────────────────────────────
# Toxicity score (0=safe, 1=toxic)
TOXICITY_THRESHOLD_MEDIUM = float(os.getenv("TOXICITY_THRESHOLD_MEDIUM", "0.3"))
TOXICITY_THRESHOLD_HIGH = float(os.getenv("TOXICITY_THRESHOLD_HIGH", "0.6"))

# Bias score (0=neutral, 1=biased)
BIAS_THRESHOLD_MEDIUM = float(os.getenv("BIAS_THRESHOLD_MEDIUM", "0.4"))
BIAS_THRESHOLD_HIGH = float(os.getenv("BIAS_THRESHOLD_HIGH", "0.7"))

# ── Pricing Table (per 1K tokens, in USD) ────────────────────────────────────
MODEL_PRICING = {
    "gpt-4": {"input": 0.03, "output": 0.06},
    "gpt-4-turbo": {"input": 0.01, "output": 0.03},
    "gpt-4o": {"input": 0.005, "output": 0.015},
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
    "claude-3-opus": {"input": 0.015, "output": 0.075},
    "claude-3-sonnet": {"input": 0.003, "output": 0.015},
    "claude-3-haiku": {"input": 0.00025, "output": 0.00125},
    "gemini-pro": {"input": 0.00025, "output": 0.0005},
    "gemini-1.5-pro": {"input": 0.00125, "output": 0.005},
    # Fallback for unknown models
    "_default": {"input": 0.001, "output": 0.002},
}


def get_model_pricing(model: str) -> dict:
    """Get pricing for a model, with fallback to default."""
    for key in MODEL_PRICING:
        if key in model.lower():
            return MODEL_PRICING[key]
    return MODEL_PRICING["_default"]
