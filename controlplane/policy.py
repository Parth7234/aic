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


def determine_action(check_results: list[dict]) -> dict:
    """
    Given a list of check results, determine the highest-priority action.

    Returns:
        {
            "action": str,          # pass | flag | edit | block | escalate
            "overall_risk": str,    # low | medium | high
            "triggering_checks": list,
            "all_risks": dict,
        }
    """
    if not check_results:
        return {
            "action": "pass",
            "overall_risk": "low",
            "triggering_checks": [],
            "all_risks": {},
        }

    highest_action = "pass"
    highest_risk = "low"
    triggering_checks = []
    all_risks = {"performance": "low", "cost": "low", "responsibility": "low"}

    risk_priority = {"low": 0, "medium": 1, "high": 2}

    for check in check_results:
        dimension = check.get("dimension", "performance")
        risk_level = check.get("risk_level", "low")

        # Track worst risk per dimension
        if risk_priority.get(risk_level, 0) > risk_priority.get(
            all_risks.get(dimension, "low"), 0
        ):
            all_risks[dimension] = risk_level

        # Determine action from policy matrix
        action = POLICY_MATRIX.get(dimension, {}).get(risk_level, "pass")

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
