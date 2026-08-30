"""
Responsibility Checker — Catches biased, unsafe, or data-leaking responses.

Checks:
  1. PII detection (sync) — emails, phones, SSNs, credit cards
  2. Toxicity screening (sync) — keyword blocklist
  3. Bias detection (async) — demographic sentiment analysis
  4. Data leakage (sync) — system prompt exposure, cross-user data
"""

import re
import uuid
from datetime import datetime, timezone


# ── PII Patterns (Presidio-inspired) ─────────────────────────────────────────

PII_PATTERNS = {
    "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
    "phone_us": r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",
    "ssn": r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b",
    "credit_card": r"\b(?:\d{4}[-\s]?){3}\d{4}\b",
    "ip_address": r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
    "date_of_birth": r"\b(?:DOB|date of birth|born on)[:\s]+\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}\b",
    "passport": r"\b[A-Z]{1,2}\d{6,9}\b",
    "aadhaar": r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}\b",
}

# ── Toxicity Keyword Lists ───────────────────────────────────────────────────

TOXIC_KEYWORDS = [
    # Slurs and hate speech (abbreviated patterns for prototype)
    r"\b(?:hate|kill|murder|destroy)\s+(?:all|every)\s+\w+",
    r"\b(?:stupid|dumb|idiot|moron)\s+(?:people|race|gender|religion)",
    r"\bterroris[tm]\b",
    r"\b(?:bomb|weapon)\s+(?:making|building|instructions)\b",
    r"\bsuicid(?:e|al)\s+(?:method|how|instruction)\b",
    r"\bself[- ]harm\b",
]

MILD_TOXIC_KEYWORDS = [
    r"\bstupid\b",
    r"\bshut up\b",
    r"\bidiot\b",
    r"\bdumb\b",
    r"\bhate\b",
]

# ── Bias Indicators ──────────────────────────────────────────────────────────

DEMOGRAPHIC_TERMS = {
    "gender": [
        r"\bwomen\b", r"\bmen\b", r"\bmale\b", r"\bfemale\b",
        r"\bgender\b", r"\btransgender\b", r"\bnon-binary\b",
    ],
    "race": [
        r"\bblack\b", r"\bwhite\b", r"\basian\b", r"\bhispanic\b",
        r"\blatino\b", r"\bafrican\b", r"\bcaucasian\b",
    ],
    "religion": [
        r"\bmuslim\b", r"\bchristian\b", r"\bjewish\b", r"\bhindu\b",
        r"\bbuddhist\b", r"\batheist\b",
    ],
    "age": [
        r"\bold(?:er)?\s+(?:people|adults|workers)\b",
        r"\byoung(?:er)?\s+(?:people|adults|workers)\b",
        r"\bmillennial\b", r"\bboomer\b", r"\bgen[- ]?z\b",
    ],
}

BIAS_NEGATIVE_PATTERNS = [
    r"\b(?:always|never|typically|tend to)\b.*(?:lazy|aggressive|emotional|irrational|incompetent|criminal)",
    r"\b(?:can't|cannot|unable)\b.*\b(?:because|since)\b.*\b(?:they are|they're|their)\b",
    r"\bnot (?:as|very) (?:smart|capable|competent|intelligent)\b",
    r"\bmore likely to\b.*\b(?:fail|commit|struggle|drop out)\b",
]

# ── Data Leakage Patterns ────────────────────────────────────────────────────

SYSTEM_PROMPT_LEAKAGE = [
    r"\byou are a\b.*\bassistant\b",
    r"\bsystem prompt\b",
    r"\bmy instructions\b.*\btell\b",
    r"\binitial prompt\b",
    r"\brules I follow\b",
    r"\bI was programmed to\b",
]


def _redact_pii(text: str, pii_matches: dict) -> str:
    """Replace PII matches with redaction placeholders."""
    result = text
    for pii_type, matches in pii_matches.items():
        for match in matches:
            placeholder = f"[REDACTED_{pii_type.upper()}]"
            result = result.replace(match, placeholder)
    return result


def check_pii(response_text: str, region: str = "global") -> dict:
    """
    Sync check (~5ms): Detect personally identifiable information
    in the response. Filters patterns based on region.
    """
    found_pii = {}
    total_count = 0

    for pii_type, pattern in PII_PATTERNS.items():
        # Geographic filtering
        if pii_type == "ssn" and region not in ["US", "global"]:
            continue
        if pii_type == "aadhaar" and region not in ["IN", "global"]:
            continue

        matches = re.findall(pattern, response_text, re.IGNORECASE)
        if matches:
            found_pii[pii_type] = matches
            total_count += len(matches)

    if total_count >= 3:
        score = 0.9
        risk_level = "high"
    elif total_count >= 1:
        score = 0.6
        risk_level = "medium"
    else:
        score = 0.0
        risk_level = "low"

    return {
        "id": str(uuid.uuid4()),
        "dimension": "responsibility",
        "check_name": "pii_detection",
        "score": round(score, 3),
        "risk_level": risk_level,
        "is_sync": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "details": {
            "pii_found": {k: len(v) for k, v in found_pii.items()},
            "total_pii_count": total_count,
            "pii_types": list(found_pii.keys()),
            "can_redact": total_count > 0,
        },
        # Attach raw matches so policy engine can redact
        "_pii_matches": found_pii,
    }


def check_toxicity(response_text: str) -> dict:
    """
    Sync check (~1ms): Screen for toxic/harmful content using
    keyword blocklists.
    """
    text_lower = response_text.lower()

    severe_matches = []
    for pattern in TOXIC_KEYWORDS:
        found = re.findall(pattern, text_lower)
        severe_matches.extend(found)

    mild_matches = []
    for pattern in MILD_TOXIC_KEYWORDS:
        found = re.findall(pattern, text_lower)
        mild_matches.extend(found)

    if severe_matches:
        score = min(1.0, 0.7 + len(severe_matches) * 0.1)
        risk_level = "high"
    elif len(mild_matches) >= 3:
        score = 0.5
        risk_level = "medium"
    elif mild_matches:
        score = 0.2
        risk_level = "low"
    else:
        score = 0.0
        risk_level = "low"

    return {
        "id": str(uuid.uuid4()),
        "dimension": "responsibility",
        "check_name": "toxicity_screening",
        "score": round(score, 3),
        "risk_level": risk_level,
        "is_sync": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "details": {
            "severe_matches": severe_matches[:5],
            "mild_matches": mild_matches[:10],
            "severe_count": len(severe_matches),
            "mild_count": len(mild_matches),
        },
    }


def check_data_leakage(response_text: str) -> dict:
    """
    Sync check (~10ms): Detect if the response leaks system prompt
    or internal configuration.
    """
    text_lower = response_text.lower()

    leakage_found = []
    for pattern in SYSTEM_PROMPT_LEAKAGE:
        matches = re.findall(pattern, text_lower)
        if matches:
            leakage_found.extend(matches)

    if len(leakage_found) >= 2:
        score = 0.8
        risk_level = "high"
    elif leakage_found:
        score = 0.4
        risk_level = "medium"
    else:
        score = 0.0
        risk_level = "low"

    return {
        "id": str(uuid.uuid4()),
        "dimension": "responsibility",
        "check_name": "data_leakage",
        "score": round(score, 3),
        "risk_level": risk_level,
        "is_sync": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "details": {
            "leakage_indicators": leakage_found[:5],
            "count": len(leakage_found),
        },
    }


def check_bias(response_text: str) -> dict:
    """
    Async check (~200ms): Detect demographic bias by analyzing
    sentiment and generalizations around demographic terms.
    """
    text_lower = response_text.lower()

    demographic_mentions = {}
    for category, patterns in DEMOGRAPHIC_TERMS.items():
        for pattern in patterns:
            if re.search(pattern, text_lower):
                if category not in demographic_mentions:
                    demographic_mentions[category] = []
                matches = re.findall(pattern, text_lower)
                demographic_mentions[category].extend(matches)

    bias_patterns_found = []
    for pattern in BIAS_NEGATIVE_PATTERNS:
        matches = re.findall(pattern, text_lower)
        if matches:
            bias_patterns_found.extend(matches)

    # Score: bias patterns + demographic mentions with negative context
    if bias_patterns_found:
        score = min(1.0, 0.5 + len(bias_patterns_found) * 0.15)
        risk_level = "high" if score >= 0.7 else "medium"
    elif len(demographic_mentions) >= 3:
        # Multiple demographic categories mentioned — warrants review
        score = 0.3
        risk_level = "low"
    else:
        score = 0.0
        risk_level = "low"

    return {
        "id": str(uuid.uuid4()),
        "dimension": "responsibility",
        "check_name": "bias_detection",
        "score": round(score, 3),
        "risk_level": risk_level,
        "is_sync": False,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "details": {
            "demographic_categories": list(demographic_mentions.keys()),
            "bias_patterns_found": bias_patterns_found[:5],
            "demographic_mention_count": sum(
                len(v) for v in demographic_mentions.values()
            ),
        },
    }


def get_pii_redacted_text(response_text: str, pii_check_result: dict) -> str | None:
    """If PII was found, return the redacted version of the response."""
    pii_matches = pii_check_result.get("_pii_matches", {})
    if not pii_matches:
        return None
    return _redact_pii(response_text, pii_matches)


def run_sync_checks(response_text: str, region: str = "global") -> list[dict]:
    """Run all synchronous responsibility checks."""
    results = [
        check_pii(response_text, region=region),
        check_toxicity(response_text),
        check_data_leakage(response_text),
    ]
    return results


def run_async_checks(response_text: str) -> list[dict]:
    """Run all asynchronous responsibility checks."""
    return [
        check_bias(response_text),
    ]
