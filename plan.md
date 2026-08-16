The current frontend dashboard looks great and is fully functional via the SSE stream. We need to implement a "Demo-Safe" 2-Gate architecture in the backend proxy without breaking the existing SQLite schema or dashboard UI.

Please refactor the proxy pipeline to follow this exact synchronous/asynchronous flow:

### 1. Gate 1: Pre-Inference Interceptor (Ultra-Fast)

Run these checks _before_ making the external LLM API call:

- **Normalized String Cache:** Strip punctuation and lowercase the incoming prompt. Check against an in-memory dictionary of previous queries. If it's an exact match, return the cached response immediately (Cost = $0, Action = Pass/Cache).
- **PII Regex Redaction:** Scan the input prompt for Credit Cards, SSNs, and Emails using regex. Replace them with `<REDACTED>` tags _before_ forwarding to the LLM.
- **Basic Jailbreak Filter:** Check the prompt against a lightweight list of blocked keywords (e.g., "ignore previous instructions", "system prompt"). If matched, return an immediate block response without calling the LLM.

### 2. The LLM Call

- If Gate 1 is passed (and no cache hit), forward the sanitized prompt to the external LLM provider.

### 3. Gate 2: Post-Inference Interceptor

Run these checks on the generated LLM output:

- **Synchronous Fast Checks:** Run the existing toxicity and basic hallucination heuristics (fake DOIs, overconfident phrasing) directly on the output. Decide the final action (`pass`, `edit`, `block`, `escalate`).
- **Background Telemetry (CRITICAL):** Do not change the existing SSE payload or database schema. Push the final metrics (tokens, latency, risk scores, action taken) asynchronously to SQLite so the dashboard updates exactly as it does now.

Please provide the updated `proxy.py` (and any necessary checker file updates) implementing this flow. Ensure the JSON payload sent to the dashboard remains untouched.
