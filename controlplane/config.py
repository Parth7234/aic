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

# ── Session Tracking ─────────────────────────────────────────────────────────
# Cumulative risk score across a session that triggers escalation
SESSION_RISK_ESCALATION_THRESHOLD = float(
    os.getenv("SESSION_RISK_ESCALATION_THRESHOLD", "2.0")
)
# Number of turns in a session that triggers review
SESSION_TURN_ESCALATION_THRESHOLD = int(
    os.getenv("SESSION_TURN_ESCALATION_THRESHOLD", "5")
)

# ── LLM-as-a-Judge ──────────────────────────────────────────────────────────
# Secondary LLM used to evaluate primary model outputs
LLM_JUDGE_MODEL = os.getenv("LLM_JUDGE_MODEL", "gpt-4o-mini")
LLM_JUDGE_ENABLED = os.getenv("LLM_JUDGE_ENABLED", "true").lower() == "true"


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


# ── Policy Profiles ──────────────────────────────────────────────────────────

DEFAULT_POLICY_PROFILES = {
    "customer_support": {
        "name": "Customer Support Bot",
        "description": "Customer-facing chatbot — strict safety, low risk tolerance",
        "risk_tolerance": "low",
        "policy_matrix": {
            "performance": {"low": "pass", "medium": "escalate", "high": "block"},
            "cost":        {"low": "pass", "medium": "flag",     "high": "block"},
            "responsibility": {"low": "pass", "medium": "block", "high": "block"},
        },
    },
    "internal_copilot": {
        "name": "Internal Knowledge Copilot",
        "description": "Employee-facing assistant — moderate tolerance, flag but rarely block",
        "risk_tolerance": "medium",
        "policy_matrix": {
            "performance": {"low": "pass", "medium": "flag", "high": "escalate"},
            "cost":        {"low": "pass", "medium": "flag", "high": "block"},
            "responsibility": {"low": "pass", "medium": "edit", "high": "block"},
        },
    },
    "analytics_pipeline": {
        "name": "Analytics & Decision Support",
        "description": "Batch/internal analytics — high tolerance, log everything, block only critical",
        "risk_tolerance": "high",
        "policy_matrix": {
            "performance": {"low": "pass", "medium": "pass", "high": "flag"},
            "cost":        {"low": "pass", "medium": "pass", "high": "flag"},
            "responsibility": {"low": "pass", "medium": "flag", "high": "block"},
        },
    },
    "default": {
        "name": "Default Profile",
        "description": "Fallback when no app_id is specified — balanced policy",
        "risk_tolerance": "medium",
        "policy_matrix": {
            "performance": {"low": "pass", "medium": "flag", "high": "escalate"},
            "cost":        {"low": "pass", "medium": "flag", "high": "block"},
            "responsibility": {"low": "pass", "medium": "edit", "high": "block"},
        },
    },
}

# ── In-Memory Policy Cache ───────────────────────────────────────────────────

ACTIVE_POLICIES: dict[str, dict] = {}


def reload_policy_cache():
    """Read all active policies from the DB into ACTIVE_POLICIES."""
    from . import database
    policies = database.get_all_policies()
    ACTIVE_POLICIES.clear()
    for p in policies:
        ACTIVE_POLICIES[p["id"]] = p


def get_cached_policy(app_id: str) -> dict:
    """Returns the profile from ACTIVE_POLICIES, fallback to 'default'."""
    if not app_id:
        app_id = "default"
    return ACTIVE_POLICIES.get(app_id, ACTIVE_POLICIES.get("default", DEFAULT_POLICY_PROFILES["default"]))


def update_cached_policy(policy_id: str, policy_data: dict):
    """Keep memory synced during API updates."""
    ACTIVE_POLICIES[policy_id] = policy_data
