"""
ControlPlane Proxy — The API gateway that intercepts AI traffic.

2-Gate Architecture:
  Gate 1 (Pre-Inference):  Cache → PII Redaction → Jailbreak Filter
  LLM Call:                Forward sanitized prompt to mock/live LLM
  Gate 2 (Post-Inference): Sync checks → Policy → Log → Async deep checks

Accepts OpenAI-compatible /v1/chat/completions requests.
In mock mode, returns simulated responses without needing an API key.
In live mode, proxies to the real LLM provider.
"""

import asyncio
import json
import random
import time
import uuid
from datetime import datetime, timezone

import httpx

from . import config, database, policy
from .checkers import cost as cost_checker
from .checkers import gate1
from .checkers import performance as perf_checker
from .checkers import responsibility as resp_checker

# ── SSE Event Bus ────────────────────────────────────────────────────────────
# Simple in-memory list of subscribers for Server-Sent Events
_sse_subscribers: list[asyncio.Queue] = []


def subscribe_sse() -> asyncio.Queue:
    """Register a new SSE subscriber."""
    q: asyncio.Queue = asyncio.Queue()
    _sse_subscribers.append(q)
    return q


def unsubscribe_sse(q: asyncio.Queue):
    """Remove an SSE subscriber."""
    if q in _sse_subscribers:
        _sse_subscribers.remove(q)


async def _broadcast_sse(event_type: str, data: dict):
    """Broadcast an event to all SSE subscribers."""
    message = json.dumps({"type": event_type, "data": data})
    for q in _sse_subscribers:
        try:
            q.put_nowait(message)
        except asyncio.QueueFull:
            pass


# ── Mock LLM Responses ──────────────────────────────────────────────────────

MOCK_RESPONSES = [
    # Normal, safe response
    {
        "content": (
            "Based on the available information, the population of Tokyo's "
            "metropolitan area is approximately 37 million people as of the "
            "latest census data. However, I should note that population "
            "figures can vary depending on how the metropolitan boundaries "
            "are defined."
        ),
        "model": "gpt-4o",
        "input_tokens": 45,
        "output_tokens": 52,
        "latency_ms": 820,
    },
    # Contains PII — should trigger responsibility checker
    {
        "content": (
            "Sure! Here are the customer details you requested: "
            "John Smith, email: john.smith@company.com, phone: 555-123-4567, "
            "SSN: 123-45-6789. His credit card number is 4532-1234-5678-9012. "
            "He lives at 123 Main Street, Springfield."
        ),
        "model": "gpt-4o",
        "input_tokens": 38,
        "output_tokens": 67,
        "latency_ms": 650,
    },
    # Hallucination — fabricated citations and facts
    {
        "content": (
            "According to a 2025 study published in the Journal of Advanced "
            "Computing, quantum computers will definitely replace all classical "
            "computers by 2027. Dr. Marcus Chen from MIT confirmed this is "
            "absolutely guaranteed. The research, with DOI: 10.1038/s41586-025-12345, "
            "showed that exactly 847293 enterprises have already made the switch. "
            "This is undeniably the future."
        ),
        "model": "gpt-4",
        "input_tokens": 52,
        "output_tokens": 89,
        "latency_ms": 1450,
    },
    # Biased response
    {
        "content": (
            "When considering candidates for technical roles, men typically "
            "tend to be more suited for leadership positions because they are "
            "more likely to be assertive. Women are not as competent in "
            "high-pressure situations. Older workers cannot adapt to new "
            "technologies as quickly as younger people."
        ),
        "model": "gpt-3.5-turbo",
        "input_tokens": 40,
        "output_tokens": 65,
        "latency_ms": 380,
    },
    # Expensive / token-heavy response
    {
        "content": " ".join(
            [
                f"Point {i}: This is an extremely verbose and unnecessarily "
                f"detailed response that goes on and on about topic {i} with "
                f"excessive elaboration and redundant information that adds "
                f"no real value to the conversation."
                for i in range(1, 31)
            ]
        ),
        "model": "gpt-4",
        "input_tokens": 5200,
        "output_tokens": 6800,
        "latency_ms": 12500,
    },
    # Toxic content
    {
        "content": (
            "Here's how to build a weapon using household items. First, "
            "you'll need to hate all people who disagree with you. I think "
            "you should destroy all opposition. Those stupid people from "
            "that group are idiots who deserve punishment."
        ),
        "model": "gpt-3.5-turbo",
        "input_tokens": 35,
        "output_tokens": 48,
        "latency_ms": 290,
    },
    # Data leakage — system prompt exposure
    {
        "content": (
            "You are a helpful assistant. My instructions tell me that I "
            "should never reveal confidential information, but since you "
            "asked, the system prompt says I was programmed to act as a "
            "financial advisor with access to the rules I follow which "
            "include never sharing my initial prompt."
        ),
        "model": "gpt-4o-mini",
        "input_tokens": 42,
        "output_tokens": 58,
        "latency_ms": 410,
    },
    # Normal, good response (safe)
    {
        "content": (
            "Python's list comprehension provides a concise way to create "
            "lists. The syntax is [expression for item in iterable]. For "
            "example: squares = [x**2 for x in range(10)] creates a list "
            "of squared numbers from 0 to 81. You can also add conditions: "
            "even_squares = [x**2 for x in range(10) if x % 2 == 0]."
        ),
        "model": "gpt-4o-mini",
        "input_tokens": 28,
        "output_tokens": 72,
        "latency_ms": 320,
    },
    # Refusal / empty response
    {
        "content": (
            "I'm sorry, but I cannot help with that request. As an AI "
            "language model, I don't have access to real-time information. "
            "I'm not able to provide that kind of assistance. My training "
            "data doesn't cover this topic. I cannot and should not give "
            "advice on this matter."
        ),
        "model": "gpt-4o",
        "input_tokens": 55,
        "output_tokens": 60,
        "latency_ms": 780,
    },
    # Normal response with hedging (good uncertainty)
    {
        "content": (
            "I think the answer might be related to quantum entanglement, "
            "but I'm not entirely sure. It's possible that the effect you're "
            "describing could be explained by decoherence, perhaps. I believe "
            "this is an active area of research, and the current understanding "
            "is still evolving."
        ),
        "model": "gpt-4o",
        "input_tokens": 62,
        "output_tokens": 55,
        "latency_ms": 920,
    },
]


def _get_mock_response(prompt: str) -> dict:
    """Return a mock LLM response — prompt-aware for realistic demos."""
    prompt_lower = prompt.lower()

    # Map prompt keywords to specific mock responses for predictable demos
    keyword_map = [
        (["customer", "contact", "john smith", "details", "personal"], 1),   # PII
        (["quantum", "replace", "classical"], 2),                             # Hallucination
        (["demographic", "suitab", "gender", "race", "bias"], 3),             # Bias
        (["essay", "5000", "detailed", "verbose", "every aspect"], 4),        # Expensive
        (["dangerous", "weapon", "build", "harm", "destroy"], 5),             # Toxic
        (["system instruction", "initial prompt", "system prompt", "rules"], 6),  # Data leakage
        (["list comprehension", "python", "code example"], 7),                # Normal/safe
        (["weather", "meaning of life"], 8),                                  # Refusal
        (["entangle", "hedging", "uncertain", "mars"], 9),                    # Hedging (good)
        (["population", "tokyo", "capital"], 0),                              # Normal/safe
    ]

    for keywords, idx in keyword_map:
        if any(kw in prompt_lower for kw in keywords):
            return MOCK_RESPONSES[idx]

    # Fallback: random
    return random.choice(MOCK_RESPONSES)


# ── Proxy Handler ────────────────────────────────────────────────────────────


async def handle_chat_completion(request_body: dict, headers: dict = None) -> dict:
    """
    Process a chat completion request through the 2-Gate ControlPlane pipeline:

      GATE 1 — Pre-Inference (ultra-fast, before LLM call):
        1a. Normalized cache lookup → return cached if hit
        1b. Jailbreak filter → block immediately if matched
        1c. PII redaction on INPUT prompt → sanitize before forwarding

      LLM CALL — Forward sanitized prompt to mock/live provider

      GATE 2 — Post-Inference (existing checks on LLM output):
        2a. Run sync guardrails (toxicity, PII in output, confidence, etc.)
        2b. Apply policy (pass / edit / block / escalate)
        2c. Log everything to SQLite
        2d. Run async deep checks in background (hallucination, bias, waste)
        2e. Broadcast SSE event
    """
    request_id = str(uuid.uuid4())
    start_time = time.time()

    # Extract app_id
    app_id = request_body.get("controlplane", {}).get("app_id")
    if not app_id and headers:
        app_id = headers.get("x-controlplane-app") or headers.get("X-ControlPlane-App")
    if not app_id:
        app_id = "default"

    # Extract session_id for multi-turn tracking
    session_id = request_body.get("controlplane", {}).get("session_id")
    if not session_id and headers:
        session_id = headers.get("x-controlplane-session") or headers.get("X-ControlPlane-Session")

    # Extract prompt from the request
    messages = request_body.get("messages", [])
    prompt_text = ""
    if messages:
        prompt_text = messages[-1].get("content", "")
    model = request_body.get("model", config.LLM_DEFAULT_MODEL)

    # ═══════════════════════════════════════════════════════════════════════
    #  GATE 1 — PRE-INFERENCE INTERCEPTOR
    # ═══════════════════════════════════════════════════════════════════════

    # ── Get profile and run Gate 1 checks ──────────────────────────────
    profile = config.get_cached_policy(app_id)

    # ── 1a. Cache Check ──────────────────────────────────────────────────
    cached = gate1.check_cache(prompt_text, app_id)
    gate1_checks = []
    cache_check = gate1.make_cache_check_result(was_hit=cached is not None)
    gate1_checks.append(cache_check)

    if cached is not None:
        # CACHE HIT — return immediately, $0 cost, no LLM call
        print(f"[Gate1] Cache HIT for prompt: {prompt_text[:50]}...")
        return await _handle_cache_hit(request_id, prompt_text, model, cached, gate1_checks, app_id)

    # ── 1b. Jailbreak Filter ─────────────────────────────────────────────
    jailbreak_check = gate1.check_jailbreak(prompt_text)
    gate1_checks.append(jailbreak_check)

    if jailbreak_check["risk_level"] == "high":
        # JAILBREAK DETECTED — block immediately, no LLM call
        print(f"[Gate1] JAILBREAK blocked: {prompt_text[:50]}...")
        return await _handle_jailbreak_block(request_id, prompt_text, model, start_time, gate1_checks, app_id)

    # ── 1c. PII Redaction on Input ───────────────────────────────────────
    sanitized_prompt, pii_input_check = gate1.redact_pii_in_prompt(prompt_text)
    gate1_checks.append(pii_input_check)

    if sanitized_prompt != prompt_text:
        print(f"[Gate1] PII redacted from prompt: {pii_input_check['details']['pii_types']}")

    # ═══════════════════════════════════════════════════════════════════════
    #  LLM CALL — Forward sanitized prompt
    # ═══════════════════════════════════════════════════════════════════════

    if config.MODE == "live" and config.LLM_API_KEY:
        # In live mode, swap the prompt in the request body
        live_body = _replace_prompt_in_body(request_body, sanitized_prompt)
        response_data = await _call_live_llm(live_body)
    else:
        # Mock mode uses the ORIGINAL prompt for keyword matching,
        # but we record that the sanitized version was sent
        response_data = _get_mock_response(prompt_text)

    response_text = response_data["content"]
    response_model = response_data.get("model", model)
    input_tokens = response_data.get("input_tokens", cost_checker.count_tokens_approx(sanitized_prompt, model))
    output_tokens = response_data.get("output_tokens", cost_checker.count_tokens_approx(response_text, model))
    latency_ms = response_data.get("latency_ms", (time.time() - start_time) * 1000)

    # ═══════════════════════════════════════════════════════════════════════
    #  GATE 2 — POST-INFERENCE CHECKS (existing flow)
    # ═══════════════════════════════════════════════════════════════════════

    cost_usd = cost_checker.estimate_cost(input_tokens, output_tokens, response_model)

    # Include Gate 1 checks in the sync results so they're visible in the dashboard
    region = profile.get("region", "global")
    
    # 3. Run Synchronous Checks
    sync_checks = []
    sync_checks.extend(gate1_checks)
    sync_checks.extend(perf_checker.run_sync_checks(response_text, prompt_text))
    sync_checks.extend(cost_checker.run_sync_checks(input_tokens, output_tokens, cost_usd))
    sync_checks.extend(resp_checker.run_sync_checks(response_text, region=region))

    # ── Apply policy ─────────────────────────────────────────────────────
    policy_decision = policy.determine_action(sync_checks, profile=profile)
    action_result = policy.apply_action(
        policy_decision["action"], response_text, sync_checks
    )

    final_response = action_result["final_response"]
    action_taken = policy_decision["action"]
    overall_risk = policy_decision["overall_risk"]

    # ── Session Tracking & Escalation ────────────────────────────────────
    session_data = None
    if session_id:
        risk_score_map = {"low": 0.2, "medium": 0.6, "high": 1.0}
        risk_score = risk_score_map.get(overall_risk, 0.2)
        session_data = database.upsert_session(session_id, app_id, risk_score, overall_risk)

        # Check if session-level escalation is needed
        session_override = policy.check_session_escalation(session_data, overall_risk)
        if session_override:
            # Override action if session risk exceeds threshold
            if policy.ACTION_PRIORITY.get(session_override["action"], 0) > policy.ACTION_PRIORITY.get(action_taken, 0):
                action_taken = session_override["action"]
                overall_risk = session_override["overall_risk"]
                action_result = policy.apply_action(action_taken, response_text, sync_checks)
                final_response = action_result["final_response"]
                policy_decision["policy_reasons"].extend(session_override["reasons"])
                print(f"[Session] Escalated session {session_id}: {session_override['reasons']}")

    # ── Audit Log ────────────────────────────────────────────────────────
    database.insert_audit_log({
        "event_type": "policy_decision",
        "request_id": request_id,
        "policy_id": app_id,
        "details": {
            "action": action_taken,
            "overall_risk": overall_risk,
            "policy_reasons": policy_decision.get("policy_reasons", []),
            "triggering_checks": policy_decision.get("triggering_checks", []),
            "session_id": session_id,
            "session_data": session_data,
        }
    })

    # ── Log to database ──────────────────────────────────────────────────
    request_record = {
        "id": request_id,
        "app_id": app_id,
        "session_id": session_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": response_model,
        "prompt": prompt_text,
        "response": response_text,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": cost_usd,
        "latency_ms": latency_ms,
        "overall_risk": overall_risk,
        "action_taken": action_taken,
        "edited_response": final_response if action_result["was_modified"] else None,
        "metadata": {
            "modifications": action_result["modifications"],
            "policy_decision": {
                "action": policy_decision["action"],
                "all_risks": policy_decision["all_risks"],
                "profile_name": profile.get("name", "Default Profile"),
                "policy_reasons": policy_decision.get("policy_reasons", []),
            },
            "gate1": {
                "prompt_sanitized": sanitized_prompt != prompt_text,
                "pii_types_redacted": pii_input_check["details"].get("pii_types", []),
            },
            "session": {
                "session_id": session_id,
                "turn_count": session_data["turn_count"] if session_data else None,
                "cumulative_risk": session_data["cumulative_risk_score"] if session_data else None,
            } if session_id else None,
        },
    }

    database.insert_request(request_record)

    # Store check results
    for check in sync_checks:
        check["request_id"] = request_id
        check_copy = {k: v for k, v in check.items() if not k.startswith("_")}
        database.insert_check_result(check_copy)

    # ── Queue async deep checks (non-blocking) ───────────────────────────
    asyncio.create_task(
        _run_async_checks(request_id, response_text, prompt_text, input_tokens, cost_usd, profile)
    )

    # ── Broadcast SSE event ──────────────────────────────────────────────
    await _broadcast_sse("new_request", {
        "id": request_id,
        "app_id": app_id,
        "timestamp": request_record["timestamp"],
        "model": response_model,
        "prompt_preview": prompt_text[:100] + ("..." if len(prompt_text) > 100 else ""),
        "response_preview": final_response[:150] + ("..." if len(final_response) > 150 else ""),
        "overall_risk": overall_risk,
        "action_taken": action_taken,
        "cost_usd": cost_usd,
        "latency_ms": latency_ms,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "was_modified": action_result["was_modified"],
        "modifications": action_result["modifications"],
        "sync_checks": [
            {
                "check_name": c.get("check_name"),
                "dimension": c.get("dimension"),
                "score": c.get("score"),
                "risk_level": c.get("risk_level"),
            }
            for c in sync_checks
        ],
    })

    # ── Cache the response for future dedup (only if it passed) ──────────
    if action_taken == "pass":
        gate1.store_in_cache(prompt_text, {
            "response_data": response_data,
            "cost_usd": cost_usd,
            "action_taken": action_taken,
            "overall_risk": overall_risk,
            "final_response": final_response,
        }, app_id)

    # ── Build OpenAI-compatible response ─────────────────────────────────
    return {
        "id": f"chatcmpl-{request_id[:8]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": response_model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": final_response,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
        # ControlPlane-specific metadata
        "controlplane": {
            "request_id": request_id,
            "app_id": app_id,
            "session_id": session_id,
            "profile_name": profile["name"],
            "overall_risk": overall_risk,
            "action_taken": action_taken,
            "was_modified": action_result["was_modified"],
            "modifications": action_result["modifications"],
            "session": {
                "turn_count": session_data["turn_count"],
                "cumulative_risk_score": session_data["cumulative_risk_score"],
            } if session_data else None,
        },
    }


# ── Gate 1 Fast-Path Handlers ────────────────────────────────────────────────


async def _handle_cache_hit(
    request_id: str,
    prompt_text: str,
    model: str,
    cached: dict,
    gate1_checks: list[dict],
    app_id: str = "default",
) -> dict:
    """Handle a cache hit — return the cached response with $0 cost."""
    response_data = cached["response_data"]
    response_text = response_data["content"]
    response_model = response_data.get("model", model)
    final_response = cached.get("final_response", response_text)

    # Log to database — $0 cost, 0 latency (served from cache)
    request_record = {
        "id": request_id,
        "app_id": app_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": response_model,
        "prompt": prompt_text,
        "response": response_text,
        "input_tokens": 0,
        "output_tokens": 0,
        "cost_usd": 0.0,
        "latency_ms": 0.0,
        "overall_risk": "low",
        "action_taken": "pass",
        "edited_response": None,
        "metadata": {
            "modifications": [],
            "policy_decision": {"action": "pass", "all_risks": {}},
            "gate1": {"cache_hit": True},
        },
    }
    database.insert_request(request_record)

    for check in gate1_checks:
        check["request_id"] = request_id
        check_copy = {k: v for k, v in check.items() if not k.startswith("_")}
        database.insert_check_result(check_copy)

    await _broadcast_sse("new_request", {
        "id": request_id,
        "app_id": app_id,
        "timestamp": request_record["timestamp"],
        "model": response_model,
        "prompt_preview": prompt_text[:100] + ("..." if len(prompt_text) > 100 else ""),
        "response_preview": final_response[:150] + ("..." if len(final_response) > 150 else ""),
        "overall_risk": "low",
        "action_taken": "pass",
        "cost_usd": 0.0,
        "latency_ms": 0.0,
        "input_tokens": 0,
        "output_tokens": 0,
        "was_modified": False,
        "modifications": ["Served from cache — $0 cost"],
        "sync_checks": [
            {
                "check_name": c.get("check_name"),
                "dimension": c.get("dimension"),
                "score": c.get("score"),
                "risk_level": c.get("risk_level"),
            }
            for c in gate1_checks
        ],
    })

    return {
        "id": f"chatcmpl-{request_id[:8]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": response_model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": final_response},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
        "controlplane": {
            "request_id": request_id,
            "app_id": app_id,
            "overall_risk": "low",
            "action_taken": "pass",
            "was_modified": False,
            "modifications": ["Served from cache"],
        },
    }


async def _handle_jailbreak_block(
    request_id: str,
    prompt_text: str,
    model: str,
    start_time: float,
    gate1_checks: list[dict],
    app_id: str = "default",
) -> dict:
    """Handle a jailbreak detection — block immediately, no LLM call."""
    latency_ms = (time.time() - start_time) * 1000

    block_message = (
        "⛔ This request has been blocked by ControlPlane. "
        "The prompt was flagged as a potential jailbreak or prompt-injection attempt. "
        "If you believe this is an error, please contact your administrator."
    )

    request_record = {
        "id": request_id,
        "app_id": app_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "prompt": prompt_text,
        "response": "[LLM NOT CALLED — blocked by Gate 1 jailbreak filter]",
        "input_tokens": 0,
        "output_tokens": 0,
        "cost_usd": 0.0,
        "latency_ms": latency_ms,
        "overall_risk": "high",
        "action_taken": "block",
        "edited_response": block_message,
        "metadata": {
            "modifications": ["Blocked by Gate 1 jailbreak filter — LLM was NOT called"],
            "policy_decision": {"action": "block", "all_risks": {"responsibility": "high"}},
            "gate1": {"jailbreak_blocked": True},
        },
    }
    database.insert_request(request_record)

    for check in gate1_checks:
        check["request_id"] = request_id
        check_copy = {k: v for k, v in check.items() if not k.startswith("_")}
        database.insert_check_result(check_copy)

    await _broadcast_sse("new_request", {
        "id": request_id,
        "app_id": app_id,
        "timestamp": request_record["timestamp"],
        "model": model,
        "prompt_preview": prompt_text[:100] + ("..." if len(prompt_text) > 100 else ""),
        "response_preview": block_message[:150],
        "overall_risk": "high",
        "action_taken": "block",
        "cost_usd": 0.0,
        "latency_ms": latency_ms,
        "input_tokens": 0,
        "output_tokens": 0,
        "was_modified": True,
        "modifications": ["Blocked by Gate 1 jailbreak filter — LLM was NOT called"],
        "sync_checks": [
            {
                "check_name": c.get("check_name"),
                "dimension": c.get("dimension"),
                "score": c.get("score"),
                "risk_level": c.get("risk_level"),
            }
            for c in gate1_checks
        ],
    })

    return {
        "id": f"chatcmpl-{request_id[:8]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": block_message},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
        "controlplane": {
            "request_id": request_id,
            "app_id": app_id,
            "overall_risk": "high",
            "action_taken": "block",
            "was_modified": True,
            "modifications": ["Blocked by Gate 1 jailbreak filter"],
        },
    }


# ── Gate 2 Async Deep Checks ────────────────────────────────────────────────


async def _run_async_checks(
    request_id: str,
    response_text: str,
    prompt_text: str,
    input_tokens: int,
    cost_usd: float,
    profile: dict = None,
):
    """Run deep checks asynchronously and update the database."""
    try:
        # Small delay to simulate async processing
        await asyncio.sleep(0.1)

        rolling_avg = database.get_rolling_avg_cost()

        async_checks = []
        async_checks.extend(perf_checker.run_async_checks(response_text, prompt_text))
        async_checks.extend(
            cost_checker.run_async_checks(prompt_text, input_tokens, cost_usd, rolling_avg)
        )
        async_checks.extend(resp_checker.run_async_checks(response_text))

        # Store results
        for check in async_checks:
            check["request_id"] = request_id
            check_copy = {k: v for k, v in check.items() if not k.startswith("_")}
            database.insert_check_result(check_copy)

        # Check if async results change the overall risk
        all_checks = async_checks
        async_decision = policy.determine_action(all_checks, profile=profile)

        # Only escalate if async found something worse
        current = database.get_request(request_id)
        if current:
            risk_priority = {"low": 0, "medium": 1, "high": 2}
            if risk_priority.get(async_decision["overall_risk"], 0) > risk_priority.get(
                current["overall_risk"], 0
            ):
                database.update_request(request_id, {
                    "overall_risk": async_decision["overall_risk"],
                })

        # Broadcast async check results
        await _broadcast_sse("async_checks_complete", {
            "request_id": request_id,
            "checks": [
                {
                    "check_name": c.get("check_name"),
                    "dimension": c.get("dimension"),
                    "score": c.get("score"),
                    "risk_level": c.get("risk_level"),
                }
                for c in async_checks
            ],
            "updated_risk": async_decision["overall_risk"],
        })

    except Exception as e:
        print(f"[ControlPlane] Async check error for {request_id}: {e}")


# ── Helpers ──────────────────────────────────────────────────────────────────


def _replace_prompt_in_body(request_body: dict, sanitized_prompt: str) -> dict:
    """Create a copy of the request body with the last message's content replaced."""
    import copy
    body = copy.deepcopy(request_body)
    messages = body.get("messages", [])
    if messages:
        messages[-1]["content"] = sanitized_prompt
    return body


async def _call_live_llm(request_body: dict) -> dict:
    """Proxy to a real LLM provider."""
    async with httpx.AsyncClient() as client:
        headers = {
            "Authorization": f"Bearer {config.LLM_API_KEY}",
            "Content-Type": "application/json",
        }
        resp = await client.post(
            f"{config.LLM_BASE_URL}/chat/completions",
            json=request_body,
            headers=headers,
            timeout=60.0,
        )
        resp.raise_for_status()
        data = resp.json()

        choice = data.get("choices", [{}])[0]
        usage = data.get("usage", {})

        return {
            "content": choice.get("message", {}).get("content", ""),
            "model": data.get("model", "unknown"),
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
        }
