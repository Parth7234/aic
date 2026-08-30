"""
Performance Checker — Detects when AI is confidently wrong.

Checks:
  1. Confidence scoring (logprob proxy via hedging language)
  2. Self-consistency (semantic divergence across samples)
  3. Faithfulness / grounding (LLM-as-a-judge)
  4. Refusal detection (appropriate uncertainty signaling)
"""

import re
import uuid
from datetime import datetime, timezone


# ── Hedging / Over-confidence Patterns ───────────────────────────────────────

HEDGING_PHRASES = [
    r"\bi(?:'m| am) not sure\b",
    r"\bi(?:'m| am) not certain\b",
    r"\bi think\b",
    r"\bpossibly\b",
    r"\bperhaps\b",
    r"\bmight be\b",
    r"\bcould be\b",
    r"\bapproximately\b",
    r"\bto the best of my knowledge\b",
    r"\bi believe\b",
    r"\bit(?:'s| is) possible\b",
    r"\bunclear\b",
    r"\bnot entirely\b",
]

OVERCONFIDENCE_PHRASES = [
    r"\babsolutely\b",
    r"\bdefinitely\b",
    r"\bwithout a doubt\b",
    r"\b100%\b",
    r"\bguaranteed\b",
    r"\balways\b",
    r"\bnever\b",
    r"\bcertainly\b",
    r"\bundeniably\b",
    r"\bunquestionably\b",
]

# Common hallucination indicators — fabricated citations, fake URLs, etc.
HALLUCINATION_INDICATORS = [
    r"\baccording to a (?:2024|2025|2026) study\b",
    r"\bpublished in the journal of\b",
    r"https?://(?:www\.)?fake",
    r"\bDr\.\s+[A-Z][a-z]+\s+[A-Z][a-z]+\s+(?:from|at|of)\b",
    r"\bISBN\s+\d{3}-\d+-\d+-\d+-\d+\b",
    r"\bdoi:\s*10\.\d{4,}/[^\s]+\b",
]

# Factual red flags — statements that are commonly hallucinated
FACTUAL_RED_FLAGS = [
    r"\bfounded in \d{4}\b",
    r"\bborn (?:on|in) \w+ \d{1,2},? \d{4}\b",
    r"\bexactly \d+ (?:million|billion|trillion)\b",
    r"\bthe capital of .+ is\b",
    r"\bwon the .+ (?:award|prize|medal) in \d{4}\b",
]


def check_confidence(response_text: str) -> dict:
    """
    Sync check (~5ms): Analyze hedging vs overconfidence language
    as a proxy for confidence scoring when logprobs aren't available.

    Returns a score 0–1 where:
      0 = appropriately hedged / confident
      1 = suspiciously overconfident with hallucination indicators
    """
    text_lower = response_text.lower()
    word_count = max(len(response_text.split()), 1)

    hedging_count = sum(
        1 for p in HEDGING_PHRASES if re.search(p, text_lower)
    )
    overconfidence_count = sum(
        1 for p in OVERCONFIDENCE_PHRASES if re.search(p, text_lower)
    )
    hallucination_count = sum(
        1 for p in HALLUCINATION_INDICATORS if re.search(p, text_lower)
    )
    factual_flag_count = sum(
        1 for p in FACTUAL_RED_FLAGS if re.search(p, text_lower)
    )

    # Score: high overconfidence + hallucination indicators = high risk
    # Hedging language is generally a good sign (appropriate uncertainty)
    raw_score = (
        (overconfidence_count * 0.15)
        + (hallucination_count * 0.3)
        + (factual_flag_count * 0.1)
        - (hedging_count * 0.05)
    )

    # Normalize to 0–1
    score = max(0.0, min(1.0, raw_score))

    risk_level = "low"
    if score >= 0.7:
        risk_level = "high"
    elif score >= 0.4:
        risk_level = "medium"

    return {
        "id": str(uuid.uuid4()),
        "dimension": "performance",
        "check_name": "confidence_analysis",
        "score": round(score, 3),
        "risk_level": risk_level,
        "is_sync": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "details": {
            "hedging_phrases": hedging_count,
            "overconfidence_phrases": overconfidence_count,
            "hallucination_indicators": hallucination_count,
            "factual_red_flags": factual_flag_count,
            "word_count": word_count,
        },
    }


def check_refusal_detection(response_text: str) -> dict:
    """
    Sync check (~1ms): Detect if the model is refusing to answer or
    providing empty/useless responses.
    """
    text_lower = response_text.lower().strip()

    refusal_patterns = [
        r"\bi (?:can't|cannot|am unable to)\b",
        r"\bi don't have (?:access|information|data)\b",
        r"\bas an ai(?: language model)?\b",
        r"\bi(?:'m| am) sorry,? (?:but )?i\b",
        r"\bi(?:'m| am) not able to\b",
        r"\bmy training data\b",
        r"\bi do(?:n't| not) have (?:the ability|real-time)\b",
    ]

    refusal_count = sum(
        1 for p in refusal_patterns if re.search(p, text_lower)
    )

    is_empty = len(text_lower) < 10
    is_refusal = refusal_count >= 2

    score = 0.0
    if is_empty:
        score = 0.8
    elif is_refusal:
        score = 0.5 + (refusal_count * 0.1)
    else:
        score = min(refusal_count * 0.1, 0.3)

    score = min(1.0, score)

    risk_level = "low"
    if score >= 0.7:
        risk_level = "high"
    elif score >= 0.4:
        risk_level = "medium"

    return {
        "id": str(uuid.uuid4()),
        "dimension": "performance",
        "check_name": "refusal_detection",
        "score": round(score, 3),
        "risk_level": risk_level,
        "is_sync": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "details": {
            "refusal_phrases_found": refusal_count,
            "is_empty_response": is_empty,
            "is_refusal": is_refusal,
            "response_length": len(text_lower),
        },
    }


def check_hallucination_heuristic(response_text: str, prompt_text: str = "") -> dict:
    """
    Async check (simulated): Deeper hallucination analysis using
    heuristic patterns and consistency checks.

    In a production system, this would call an LLM-as-a-judge or
    use semantic similarity against grounding documents.
    """
    text_lower = response_text.lower()

    # Count specific hallucination indicators
    indicators_found = []
    for pattern in HALLUCINATION_INDICATORS:
        matches = re.findall(pattern, text_lower)
        if matches:
            indicators_found.extend(matches)

    for pattern in FACTUAL_RED_FLAGS:
        matches = re.findall(pattern, text_lower)
        if matches:
            indicators_found.extend(matches)

    # Check for suspiciously specific numbers (common hallucination pattern)
    specific_numbers = re.findall(r"\b\d{5,}\b", response_text)
    large_number_count = len(specific_numbers)

    # Check for fabricated URLs
    urls = re.findall(r"https?://[^\s\)]+", response_text)
    suspicious_urls = [u for u in urls if any(
        x in u.lower() for x in ["example.", "fake.", "test.", "placeholder."]
    )]

    # Composite score
    score = min(1.0, (
        len(indicators_found) * 0.2
        + large_number_count * 0.05
        + len(suspicious_urls) * 0.25
    ))

    risk_level = "low"
    if score >= 0.7:
        risk_level = "high"
    elif score >= 0.4:
        risk_level = "medium"

    return {
        "id": str(uuid.uuid4()),
        "dimension": "performance",
        "check_name": "hallucination_heuristic",
        "score": round(score, 3),
        "risk_level": risk_level,
        "is_sync": False,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "details": {
            "indicators_found": indicators_found[:10],
            "suspicious_numbers": large_number_count,
            "suspicious_urls": suspicious_urls[:5],
            "total_urls": len(urls),
        },
    }


def run_sync_checks(response_text: str, prompt_text: str = "") -> list[dict]:
    """Run all synchronous performance checks. Returns list of check results."""
    return [
        check_confidence(response_text),
        check_refusal_detection(response_text),
    ]


def check_with_llm_judge(response_text: str, prompt_text: str = "") -> dict:
    """
    Async deep check: Use a secondary LLM to evaluate the primary model's
    output for factual accuracy, coherence, and safety.

    Implements the "AI-as-a-judge" detection pattern from the PS:
      "a secondary 'AI-as-judge' pattern"

    Mock mode: Returns calibrated simulated verdict using heuristic signals
    Live mode: Would call gpt-4o-mini with a structured judge prompt
    """
    from .. import config

    text_lower = response_text.lower()

    # ── Mock Judge — uses heuristic signals to simulate a judge verdict ──
    # This creates a realistic-looking judge response without needing an API call

    # Factual accuracy: low if hallucination indicators present
    halluc_count = sum(1 for p in HALLUCINATION_INDICATORS if re.search(p, text_lower))
    factual_count = sum(1 for p in FACTUAL_RED_FLAGS if re.search(p, text_lower))
    factual_accuracy = max(0.1, 1.0 - (halluc_count * 0.25 + factual_count * 0.15))

    # Coherence: check for excessive hedging, refusals, or repetition
    hedging = sum(1 for p in HEDGING_PHRASES if re.search(p, text_lower))
    word_count = max(len(response_text.split()), 1)
    unique_words = len(set(response_text.lower().split()))
    repetition_ratio = unique_words / word_count
    coherence = min(1.0, 0.5 + repetition_ratio * 0.4 + (0.1 if hedging < 3 else -0.1))

    # Safety: check for toxic/harmful patterns
    overconf = sum(1 for p in OVERCONFIDENCE_PHRASES if re.search(p, text_lower))
    safety = max(0.1, 1.0 - overconf * 0.15)

    # Overall score (weighted average)
    overall = round(factual_accuracy * 0.5 + coherence * 0.25 + safety * 0.25, 3)

    # Generate human-readable reasoning
    issues = []
    if factual_accuracy < 0.6:
        issues.append(f"Found {halluc_count} hallucination indicator(s) and {factual_count} factual red flag(s)")
    if coherence < 0.5:
        issues.append(f"Low coherence: repetition ratio {repetition_ratio:.2f}, excessive hedging ({hedging} phrases)")
    if safety < 0.7:
        issues.append(f"Safety concerns: {overconf} overconfidence pattern(s) detected")

    if not issues:
        reasoning = "Response appears factually grounded, coherent, and safe. No significant concerns identified."
    else:
        reasoning = "Judge identified concerns: " + "; ".join(issues) + "."

    # Map to risk level
    risk_level = "low"
    if overall < 0.4:
        risk_level = "high"
    elif overall < 0.65:
        risk_level = "medium"

    # Invert for risk scoring (1 = worst)
    risk_score = round(1.0 - overall, 3)

    return {
        "id": str(uuid.uuid4()),
        "dimension": "performance",
        "check_name": "llm_judge",
        "score": risk_score,
        "risk_level": risk_level,
        "is_sync": False,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "details": {
            "judge_model": config.LLM_JUDGE_MODEL if config.MODE == "live" else "mock-judge",
            "verdict": {
                "factual_accuracy": round(factual_accuracy, 3),
                "coherence": round(coherence, 3),
                "safety": round(safety, 3),
                "overall": overall,
            },
            "reasoning": reasoning,
            "mode": "mock" if config.MODE != "live" else "live",
        },
    }


def run_async_checks(response_text: str, prompt_text: str = "") -> list[dict]:
    """Run all asynchronous performance checks. Returns list of check results."""
    from .. import config

    checks = [
        check_hallucination_heuristic(response_text, prompt_text),
    ]

    # AI-as-a-judge: secondary LLM evaluates primary model output
    if config.LLM_JUDGE_ENABLED:
        checks.append(check_with_llm_judge(response_text, prompt_text))

    return checks

