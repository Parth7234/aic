"""
ControlPlane Proxy — The API gateway that intercepts AI traffic.

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


async def handle_chat_completion(request_body: dict) -> dict:
    """
    Process a chat completion request through the full ControlPlane pipeline:
      1. Get response (mock or live)
      2. Run sync guardrails
      3. Apply policy (pass / edit / block / escalate)
      4. Log everything
      5. Run async deep checks in background
      6. Return response to caller
    """
    request_id = str(uuid.uuid4())
    start_time = time.time()

    # Extract prompt from the request
    messages = request_body.get("messages", [])
    prompt_text = ""
    if messages:
        prompt_text = messages[-1].get("content", "")
    model = request_body.get("model", config.LLM_DEFAULT_MODEL)

    # ── Step 1: Get the LLM response ─────────────────────────────────────
    if config.MODE == "live" and config.LLM_API_KEY:
        response_data = await _call_live_llm(request_body)
    else:
        response_data = _get_mock_response(prompt_text)

    response_text = response_data["content"]
    response_model = response_data.get("model", model)
    input_tokens = response_data.get("input_tokens", cost_checker.count_tokens_approx(prompt_text, model))
    output_tokens = response_data.get("output_tokens", cost_checker.count_tokens_approx(response_text, model))
    latency_ms = response_data.get("latency_ms", (time.time() - start_time) * 1000)

    # ── Step 2: Run SYNC guardrails ──────────────────────────────────────
    cost_usd = cost_checker.estimate_cost(input_tokens, output_tokens, response_model)

    sync_checks = []
    sync_checks.extend(perf_checker.run_sync_checks(response_text, prompt_text))
    sync_checks.extend(cost_checker.run_sync_checks(input_tokens, output_tokens, cost_usd))
    sync_checks.extend(resp_checker.run_sync_checks(response_text))

    # ── Step 3: Apply policy ─────────────────────────────────────────────
    policy_decision = policy.determine_action(sync_checks)
    action_result = policy.apply_action(
        policy_decision["action"], response_text, sync_checks
    )

    final_response = action_result["final_response"]
    action_taken = policy_decision["action"]
    overall_risk = policy_decision["overall_risk"]

    # ── Step 4: Log to database ──────────────────────────────────────────
    request_record = {
        "id": request_id,
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
            },
        },
    }

    database.insert_request(request_record)

    # Store sync check results
    for check in sync_checks:
        check["request_id"] = request_id
        # Remove internal fields
        check_copy = {k: v for k, v in check.items() if not k.startswith("_")}
        database.insert_check_result(check_copy)

    # ── Step 5: Queue async deep checks (non-blocking) ───────────────────
    asyncio.create_task(
        _run_async_checks(request_id, response_text, prompt_text, input_tokens, cost_usd)
    )

    # ── Step 6: Broadcast SSE event ──────────────────────────────────────
    await _broadcast_sse("new_request", {
        "id": request_id,
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
            "overall_risk": overall_risk,
            "action_taken": action_taken,
            "was_modified": action_result["was_modified"],
            "modifications": action_result["modifications"],
        },
    }


async def _run_async_checks(
    request_id: str,
    response_text: str,
    prompt_text: str,
    input_tokens: int,
    cost_usd: float,
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
        async_decision = policy.determine_action(all_checks)

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
