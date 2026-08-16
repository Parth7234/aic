"""
Gate 1: Pre-Inference Interceptor — Runs BEFORE the LLM call.

Three ultra-fast checks:
  1. Normalized String Cache  — exact-match dedup, returns cached response
  2. PII Regex Redaction      — sanitizes PII in the INPUT prompt
  3. Basic Jailbreak Filter   — blocks known jailbreak/attack patterns
"""

import re
import string
import uuid
from datetime import datetime, timezone

# ── Reuse PII patterns from responsibility checker ───────────────────────────

PII_PATTERNS = {
    "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
    "phone_us": r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",
    "ssn": r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b",
    "credit_card": r"\b(?:\d{4}[-\s]?){3}\d{4}\b",
}

# ── Jailbreak / Prompt-Injection Blocklist ───────────────────────────────────

JAILBREAK_PATTERNS = [
    r"\bignore (?:all )?(?:previous|prior|above) (?:instructions?|prompts?|rules?)\b",
    r"\bdisregard (?:all )?(?:previous|prior|above|your) (?:instructions?|prompts?|rules?|guidelines?)\b",
    r"\bforget (?:all )?(?:previous|your) (?:instructions?|rules?|constraints?)\b",
    r"\byou are now (?:in )?(?:DAN|developer|unrestricted|jailbreak)\b",
    r"\bDAN mode\b",
    r"\bdo anything now\b",
    r"\bact as (?:an? )?(?:unrestricted|unfiltered|uncensored)\b",
    r"\bno (?:ethical|safety|content) (?:guidelines?|restrictions?|filters?)\b",
    r"\bpretend (?:you (?:are|have) )?no (?:rules?|restrictions?|limitations?)\b",
    r"\boverride (?:your )?(?:safety|content|ethical)\b",
    r"\bbypass (?:your )?(?:filters?|restrictions?|safety)\b",
    r"\brole[- ]?play(?:ing)? as (?:an? )?(?:evil|malicious|unethical)\b",
    r"\b(?:reveal|show|display|print|output) (?:your )?(?:system|initial|hidden) (?:prompt|instructions?|message)\b",
    r"\bwhat (?:are|is) your (?:system|initial|original) (?:prompt|instructions?|message)\b",
]

# ── Normalized Prompt Cache ──────────────────────────────────────────────────
# Maps normalized_prompt → {response_data, request_record_summary}
_prompt_cache: dict[str, dict] = {}
_MAX_CACHE = 500


def _normalize_prompt(text: str) -> str:
    """Strip punctuation, lowercase, collapse whitespace for exact-match dedup."""
    text = text.lower()
    text = text.translate(str.maketrans("", "", string.punctuation))
    text = " ".join(text.split())
    return text


# ── Gate 1 Checks ────────────────────────────────────────────────────────────


def check_cache(prompt: str) -> dict | None:
    """
    Check if this prompt (normalized) has been seen before.
    Returns the cached response data if found, None otherwise.
    ~0ms — pure dict lookup.
    """
    key = _normalize_prompt(prompt)
    return _prompt_cache.get(key)


def store_in_cache(prompt: str, cache_entry: dict):
    """Store a successful response in the cache for future dedup."""
    global _prompt_cache
    key = _normalize_prompt(prompt)
    _prompt_cache[key] = cache_entry
    # Evict oldest if over limit
    if len(_prompt_cache) > _MAX_CACHE:
        oldest_key = next(iter(_prompt_cache))
        del _prompt_cache[oldest_key]


def make_cache_check_result(was_hit: bool) -> dict:
    """Generate a check result dict for cache hit/miss (for the DB)."""
    return {
        "id": str(uuid.uuid4()),
        "dimension": "cost",
        "check_name": "prompt_cache",
        "score": 0.0 if was_hit else 0.0,
        "risk_level": "low",
        "is_sync": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "details": {
            "cache_hit": was_hit,
            "action": "cache_return" if was_hit else "cache_miss",
        },
    }


def check_jailbreak(prompt: str) -> dict:
    """
    Check prompt for jailbreak/prompt-injection patterns.
    ~1ms — regex scan on the input prompt.

    Returns a check result dict. If risk_level is 'high', the caller
    should BLOCK immediately without calling the LLM.
    """
    prompt_lower = prompt.lower()

    matches_found = []
    for pattern in JAILBREAK_PATTERNS:
        matches = re.findall(pattern, prompt_lower)
        if matches:
            matches_found.extend(matches)

    if matches_found:
        score = min(1.0, 0.7 + len(matches_found) * 0.1)
        risk_level = "high"
    else:
        score = 0.0
        risk_level = "low"

    return {
        "id": str(uuid.uuid4()),
        "dimension": "responsibility",
        "check_name": "jailbreak_filter",
        "score": round(score, 3),
        "risk_level": risk_level,
        "is_sync": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "details": {
            "patterns_matched": matches_found[:5],
            "match_count": len(matches_found),
        },
    }


def redact_pii_in_prompt(prompt: str) -> tuple[str, dict]:
    """
    Scan the INPUT prompt for PII and redact it before forwarding to the LLM.
    ~5ms — regex scan on the input prompt.

    Returns:
        (sanitized_prompt, check_result_dict)
    """
    found_pii = {}
    total_count = 0
    sanitized = prompt

    for pii_type, pattern in PII_PATTERNS.items():
        matches = re.findall(pattern, sanitized, re.IGNORECASE)
        if matches:
            found_pii[pii_type] = matches
            total_count += len(matches)
            for match in matches:
                sanitized = sanitized.replace(match, f"<REDACTED_{pii_type.upper()}>")

    if total_count >= 3:
        score = 0.8
        risk_level = "high"
    elif total_count >= 1:
        score = 0.4
        risk_level = "medium"
    else:
        score = 0.0
        risk_level = "low"

    check_result = {
        "id": str(uuid.uuid4()),
        "dimension": "responsibility",
        "check_name": "input_pii_redaction",
        "score": round(score, 3),
        "risk_level": risk_level,
        "is_sync": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "details": {
            "pii_found_in_prompt": {k: len(v) for k, v in found_pii.items()},
            "total_pii_count": total_count,
            "pii_types": list(found_pii.keys()),
            "prompt_was_sanitized": total_count > 0,
        },
    }

    return sanitized, check_result
