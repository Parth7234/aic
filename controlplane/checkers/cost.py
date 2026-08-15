"""
Cost Checker — Catches when AI is burning more compute than it should.

Checks:
  1. Token budget enforcement (sync)
  2. Cost estimation (sync)
  3. Anomaly detection vs rolling average (async)
  4. Waste detection — repeated / near-identical prompts (async)
"""

import hashlib
import uuid
from datetime import datetime, timezone

from .. import config

# ── In-memory prompt cache for waste detection ───────────────────────────────
_recent_prompts: list[dict] = []  # [{hash, timestamp, tokens}]
_MAX_RECENT = 100


def _hash_prompt(text: str) -> str:
    """Create a short hash of prompt text for similarity detection."""
    normalized = " ".join(text.lower().split())
    return hashlib.md5(normalized.encode()).hexdigest()[:12]


def count_tokens_approx(text: str, model: str = "gpt-3.5-turbo") -> int:
    """
    Count tokens approximately. Uses tiktoken if available,
    falls back to word-count heuristic (≈0.75 tokens per word).
    """
    try:
        import tiktoken
        enc = tiktoken.encoding_for_model(model)
        return len(enc.encode(text))
    except Exception:
        # Fallback: rough heuristic
        return max(1, int(len(text.split()) * 1.33))


def estimate_cost(input_tokens: int, output_tokens: int, model: str) -> float:
    """Estimate the cost of a request in USD."""
    pricing = config.get_model_pricing(model)
    cost = (
        (input_tokens / 1000) * pricing["input"]
        + (output_tokens / 1000) * pricing["output"]
    )
    return round(cost, 6)


def check_token_budget(
    input_tokens: int, output_tokens: int
) -> dict:
    """
    Sync check (~2ms): Enforce per-request token budget.
    """
    total_tokens = input_tokens + output_tokens
    budget = config.TOKEN_BUDGET_PER_REQUEST
    ratio = total_tokens / max(budget, 1)

    if ratio > 1.0:
        score = min(1.0, ratio - 0.5)
        risk_level = "high" if ratio > 1.5 else "medium"
    elif ratio > 0.8:
        score = 0.3
        risk_level = "medium"
    else:
        score = max(0.0, ratio * 0.2)
        risk_level = "low"

    return {
        "id": str(uuid.uuid4()),
        "dimension": "cost",
        "check_name": "token_budget",
        "score": round(score, 3),
        "risk_level": risk_level,
        "is_sync": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "details": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "budget": budget,
            "ratio": round(ratio, 3),
        },
    }


def check_cost_budget(cost_usd: float) -> dict:
    """
    Sync check (~1ms): Enforce per-request cost budget.
    """
    budget = config.COST_BUDGET_PER_REQUEST
    ratio = cost_usd / max(budget, 0.001)

    if ratio > 1.0:
        score = min(1.0, 0.5 + (ratio - 1.0) * 0.25)
        risk_level = "high" if ratio > 2.0 else "medium"
    else:
        score = max(0.0, ratio * 0.2)
        risk_level = "low"

    return {
        "id": str(uuid.uuid4()),
        "dimension": "cost",
        "check_name": "cost_budget",
        "score": round(score, 3),
        "risk_level": risk_level,
        "is_sync": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "details": {
            "cost_usd": cost_usd,
            "budget_usd": budget,
            "ratio": round(ratio, 3),
        },
    }


def check_cost_anomaly(cost_usd: float, rolling_avg: float) -> dict:
    """
    Async check (~10ms): Flag if request cost is an outlier
    vs the rolling average.
    """
    if rolling_avg <= 0:
        # Not enough data yet
        return {
            "id": str(uuid.uuid4()),
            "dimension": "cost",
            "check_name": "cost_anomaly",
            "score": 0.0,
            "risk_level": "low",
            "is_sync": False,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "details": {
                "cost_usd": cost_usd,
                "rolling_avg": 0,
                "multiplier": 0,
                "note": "insufficient_data",
            },
        }

    multiplier = cost_usd / rolling_avg
    threshold = config.COST_ANOMALY_MULTIPLIER

    if multiplier > threshold:
        score = min(1.0, (multiplier - threshold) * 0.2 + 0.5)
        risk_level = "high" if multiplier > threshold * 2 else "medium"
    else:
        score = max(0.0, (multiplier / threshold) * 0.2)
        risk_level = "low"

    return {
        "id": str(uuid.uuid4()),
        "dimension": "cost",
        "check_name": "cost_anomaly",
        "score": round(score, 3),
        "risk_level": risk_level,
        "is_sync": False,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "details": {
            "cost_usd": cost_usd,
            "rolling_avg": round(rolling_avg, 6),
            "multiplier": round(multiplier, 2),
            "threshold": threshold,
        },
    }


def check_waste_detection(prompt_text: str, input_tokens: int) -> dict:
    """
    Async check (~50ms): Detect repeated near-identical prompts
    that waste compute.
    """
    global _recent_prompts

    prompt_hash = _hash_prompt(prompt_text)
    now = datetime.now(timezone.utc)

    # Count how many recent prompts have the same hash
    duplicates = [
        p for p in _recent_prompts
        if p["hash"] == prompt_hash
    ]
    duplicate_count = len(duplicates)

    # Track this prompt
    _recent_prompts.append({
        "hash": prompt_hash,
        "timestamp": now.isoformat(),
        "tokens": input_tokens,
    })
    if len(_recent_prompts) > _MAX_RECENT:
        _recent_prompts.pop(0)

    # Score based on duplicate count
    if duplicate_count >= 5:
        score = 0.9
        risk_level = "high"
    elif duplicate_count >= 3:
        score = 0.6
        risk_level = "medium"
    elif duplicate_count >= 1:
        score = 0.3
        risk_level = "low"
    else:
        score = 0.0
        risk_level = "low"

    wasted_tokens = sum(p["tokens"] for p in duplicates)

    return {
        "id": str(uuid.uuid4()),
        "dimension": "cost",
        "check_name": "waste_detection",
        "score": round(score, 3),
        "risk_level": risk_level,
        "is_sync": False,
        "timestamp": now.isoformat(),
        "details": {
            "duplicate_count": duplicate_count,
            "prompt_hash": prompt_hash,
            "wasted_tokens_estimate": wasted_tokens,
            "recent_prompt_cache_size": len(_recent_prompts),
        },
    }


def run_sync_checks(
    input_tokens: int, output_tokens: int, cost_usd: float
) -> list[dict]:
    """Run all synchronous cost checks."""
    return [
        check_token_budget(input_tokens, output_tokens),
        check_cost_budget(cost_usd),
    ]


def run_async_checks(
    prompt_text: str,
    input_tokens: int,
    cost_usd: float,
    rolling_avg_cost: float,
) -> list[dict]:
    """Run all asynchronous cost checks."""
    return [
        check_cost_anomaly(cost_usd, rolling_avg_cost),
        check_waste_detection(prompt_text, input_tokens),
    ]
