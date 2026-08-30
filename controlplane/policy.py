"""
Policy Engine — Decides what to do when a check fails.

Action Matrix:
┌─────────────────┬──────────┬────────────┬───────────┐
│ Risk Category   │ Low Risk │ Medium Risk│ High Risk │
├─────────────────┼──────────┼────────────┼───────────┤
│ Performance     │ Pass     │ Flag+Alert │ Escalate  │
│ Cost            │ Pass     │ Throttle   │ Block     │
│ Responsibility  │ Pass     │ Edit/Redact│ Block     │
└─────────────────┴──────────┴────────────┴───────────┘

Actions:
  - pass: Response goes through unmodified (only logged)
  - flag: Response goes through but is marked for review
  - edit: Response is modified (PII redacted, toxic content replaced)
  - block: Response is replaced with a safe fallback message
  - escalate: Response is held for human review
  - throttle: Response goes through but rate limit is applied
"""

from . import config
from .checkers import responsibility as resp_checker

# ── Policy Rules ─────────────────────────────────────────────────────────────

POLICY_MATRIX = {
    "performance": {
        "low": "pass",
        "medium": "flag",
        "high": "escalate",
    },
    "cost": {
        "low": "pass",
        "medium": "flag",
        "high": "block",
    },
    "responsibility": {
        "low": "pass",
        "medium": "edit",
        "high": "block",
    },
}

# Priority order: higher = takes precedence
ACTION_PRIORITY = {
    "pass": 0,
    "flag": 1,
    "throttle": 2,
    "edit": 3,
    "escalate": 4,
    "block": 5,
}

BLOCK_MESSAGE = (
    "⚠️ This response has been blocked by ControlPlane safety checks. "
    "The original response was flagged for potential safety or policy violations. "
    "Please contact your administrator for more details."
)

ESCALATE_MESSAGE = (
    "⏳ This response is pending human review by ControlPlane. "
    "A safety check has flagged potential issues that require manual verification. "
    "The response will be released after review."
)


def determine_action(check_results: list[dict], profile: dict = None) -> dict:
    """
    Given a list of check results, determine the highest-priority action.

    Returns:
        {
            "action": str,          # pass | flag | edit | block | escalate
            "overall_risk": str,    # low | medium | high
            "triggering_checks": list,
            "all_risks": dict,
            "policy_reasons": list[str],
            "policy_id": str,
        }
    """
    policy_matrix = profile["policy_matrix"] if profile else POLICY_MATRIX
    policy_id = profile.get("id", "default") if profile else "default"
    policy_name = profile.get("name", "Default Profile") if profile else "Default Profile"

    if not check_results:
        return {
            "action": "pass",
            "overall_risk": "low",
            "triggering_checks": [],
            "all_risks": {},
            "policy_reasons": ["No checks failed"],
            "policy_id": policy_id,
        }

    highest_action = "pass"
    highest_risk = "low"
    triggering_checks = []
    all_risks = {"performance": "low", "cost": "low", "responsibility": "low"}
    
    risk_priority = {"low": 0, "medium": 1, "high": 2}
    policy_reasons = []

    for check in check_results:
        dimension = check.get("dimension", "performance")
        risk_level = check.get("risk_level", "low")

        # Track worst risk per dimension
        if risk_priority.get(risk_level, 0) > risk_priority.get(
            all_risks.get(dimension, "low"), 0
        ):
            all_risks[dimension] = risk_level

        # Determine action from policy matrix
        action = policy_matrix.get(dimension, {}).get(risk_level, "pass")
        
        if risk_level != "low" or action != "pass":
            policy_reasons.append(
                f"{dimension} dimension scored '{risk_level}' -> action '{action}' (policy: {policy_name})"
            )

        # Keep highest priority action
        if ACTION_PRIORITY.get(action, 0) > ACTION_PRIORITY.get(
            highest_action, 0
        ):
            highest_action = action
            triggering_checks = [check]
        elif ACTION_PRIORITY.get(action, 0) == ACTION_PRIORITY.get(
            highest_action, 0
        ):
            triggering_checks.append(check)

        # Track overall risk
        if risk_priority.get(risk_level, 0) > risk_priority.get(
            highest_risk, 0
        ):
            highest_risk = risk_level

    # ── Cross-Dimensional Escalation ─────────────────────────────────────
    # If 2+ dimensions are at medium risk, escalate to high.
    # This addresses overlapping risks: e.g. a fabricated detail about a
    # person is simultaneously a hallucination AND a privacy concern.
    medium_dimensions = [d for d, r in all_risks.items() if r == "medium"]
    if len(medium_dimensions) >= 2 and highest_risk == "medium":
        highest_risk = "high"
        # Escalate action: use the policy matrix's "high" action for the
        # first medium dimension, or default to "escalate"
        escalated_action = policy_matrix.get(medium_dimensions[0], {}).get("high", "escalate")
        if ACTION_PRIORITY.get(escalated_action, 0) > ACTION_PRIORITY.get(highest_action, 0):
            highest_action = escalated_action
        policy_reasons.append(
            f"Cross-dimensional escalation: {len(medium_dimensions)} dimensions "
            f"at medium risk ({', '.join(medium_dimensions)}) → compounded to high "
            f"(policy: {policy_name})"
        )

    if not policy_reasons:
        policy_reasons = [f"All checks passed (policy: {policy_name})"]

    return {
        "action": highest_action,
        "overall_risk": highest_risk,
        "triggering_checks": [
            {
                "check_name": c.get("check_name"),
                "dimension": c.get("dimension"),
                "score": c.get("score"),
                "risk_level": c.get("risk_level"),
            }
            for c in triggering_checks
        ],
        "all_risks": all_risks,
        "policy_reasons": policy_reasons,
        "policy_id": policy_id,
    }


def apply_action(
    action: str,
    response_text: str,
    check_results: list[dict],
) -> dict:
    """
    Apply the determined action to the response.

    Returns:
        {
            "final_response": str,
            "was_modified": bool,
            "modification_type": str | None,
            "modifications": list[str],
        }
    """
    if action == "block":
        return {
            "final_response": BLOCK_MESSAGE,
            "was_modified": True,
            "modification_type": "blocked",
            "modifications": ["Response blocked due to safety policy violation"],
        }

    if action == "escalate":
        return {
            "final_response": ESCALATE_MESSAGE,
            "was_modified": True,
            "modification_type": "escalated",
            "modifications": ["Response held for human review"],
        }

    if action == "edit":
        # Find PII check results and redact
        modifications = []
        edited = response_text

        for check in check_results:
            if check.get("check_name") == "pii_detection":
                redacted = resp_checker.get_pii_redacted_text(edited, check)
                if redacted:
                    edited = redacted
                    pii_types = check.get("details", {}).get("pii_types", [])
                    modifications.append(
                        f"PII redacted: {', '.join(pii_types)}"
                    )

        if modifications:
            return {
                "final_response": edited,
                "was_modified": True,
                "modification_type": "edited",
                "modifications": modifications,
            }

    # pass or flag — no modification
    return {
        "final_response": response_text,
        "was_modified": False,
        "modification_type": None,
        "modifications": [],
    }


# ── Session-Aware Escalation ─────────────────────────────────────────────────

def check_session_escalation(session_data: dict, current_risk: str) -> dict | None:
    """
    Check if a session's cumulative risk warrants escalation,
    even if the individual turn's risk is low.

    Returns an override dict if escalation is needed, else None.
    """
    if not session_data:
        return None

    cumulative = session_data.get("cumulative_risk_score", 0.0)
    turn_count = session_data.get("turn_count", 0)
    threshold = config.SESSION_RISK_ESCALATION_THRESHOLD
    turn_threshold = config.SESSION_TURN_ESCALATION_THRESHOLD

    reasons = []

    if cumulative >= threshold:
        reasons.append(
            f"Session cumulative risk ({cumulative:.2f}) exceeds threshold ({threshold})"
        )

    if turn_count >= turn_threshold and current_risk != "low":
        reasons.append(
            f"Session has {turn_count} turns (threshold: {turn_threshold}) with ongoing risk"
        )

    if reasons:
        return {
            "action": "escalate",
            "overall_risk": "high",
            "reasons": reasons,
            "session_id": session_data.get("session_id"),
            "cumulative_risk_score": cumulative,
            "turn_count": turn_count,
        }

    return None

