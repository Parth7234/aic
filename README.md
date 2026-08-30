# ControlPlane.ai

> **Enterprise-grade AI governance layer** — Real-time detection, policy enforcement, and observability for generative AI at scale.

ControlPlane.ai is a transparent proxy that sits between your applications and their AI providers, intercepting every request and response to enforce safety, cost, and performance policies — before risky outputs ever reach a user.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        ControlPlane.ai                              │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  GATE 1 — Pre-Inference (< 5ms, before LLM call)            │   │
│  │  ┌──────────┐  ┌───────────────┐  ┌──────────────────────┐  │   │
│  │  │  Cache    │→ │ Jailbreak     │→ │ PII Redaction        │  │   │
│  │  │  Lookup   │  │ Filter        │  │ (Input Sanitization) │  │   │
│  │  └──────────┘  └───────────────┘  └──────────────────────┘  │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                              ↓                                      │
│                    ┌──────────────────┐                             │
│                    │   LLM Provider   │  (OpenAI / Azure / etc.)    │
│                    └──────────────────┘                             │
│                              ↓                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  GATE 2 — Post-Inference                                     │   │
│  │  ┌─────────────────┐  ┌─────────────────┐                   │   │
│  │  │ SYNC (blocking)  │  │ ASYNC (bg)      │                   │   │
│  │  │ • Toxicity       │  │ • Hallucination  │                   │   │
│  │  │ • PII in output  │  │ • Bias detection │                   │   │
│  │  │ • Confidence     │  │ • Cost anomaly   │                   │   │
│  │  │ • Data leakage   │  │ • LLM-as-Judge   │                   │   │
│  │  │ • Refusal detect │  │ • Waste detect   │                   │   │
│  │  └─────────────────┘  └─────────────────┘                   │   │
│  │              ↓                                               │   │
│  │  ┌─────────────────────────────────────────────┐             │   │
│  │  │  Policy Engine                               │             │   │
│  │  │  • Per-app profiles (multi-tenant)           │             │   │
│  │  │  • Cross-dimension risk correlation          │             │   │
│  │  │  • Session-aware compounding risk            │             │   │
│  │  │  → pass | flag | edit | escalate | block     │             │   │
│  │  └─────────────────────────────────────────────┘             │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                              ↓                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Observability Layer                                         │   │
│  │  • Real-time SSE dashboard       • Audit trail              │   │
│  │  • Human review queue            • Feedback loops           │   │
│  │  • System health metrics         • Per-check accuracy       │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Key Features

### 🛡️ 2-Gate Detection Pipeline
- **Gate 1 (Pre-Inference):** Cache deduplication, jailbreak blocking, PII redaction on input — all before the LLM is called, saving cost on every blocked request.
- **Gate 2 (Post-Inference):** Sync checks (toxicity, PII, confidence, data leakage) block in real-time; async deep checks (hallucination, bias, LLM-as-judge) run in background.

### 🏢 Multi-Tenant Policy Profiles
Different AI use cases need different governance:
- **Customer Support Bot** — Strict: blocks on medium responsibility risk
- **Internal Knowledge Copilot** — Moderate: flags and edits, rarely blocks
- **Analytics Pipeline** — Permissive: logs everything, blocks only critical

Same AI output → different policy outcomes based on context. Policies are configurable at runtime via API and UI.

### 🧠 AI-as-a-Judge Detection
A secondary "judge" evaluates the primary model's output for factual accuracy, coherence, and safety — implementing the heterogeneous detection approach (not just regex).

### 🔄 Multi-Turn Session Tracking
Conversations are tracked across turns. Even if individual messages are low-risk, cumulative risk across a session can trigger escalation — addressing compounding risk in multi-turn interactions.

### 📊 Feedback Loops & System Health
- Human reviewers approve/block/release flagged responses
- Every override is classified: **false positive**, **false negative**, or **confirmed**
- Per-check accuracy rates and tuning suggestions
- Override rate and trust metrics for stakeholder reporting

### ⚡ Cross-Dimensional Risk Correlation
When 2+ risk dimensions (performance, cost, responsibility) are at medium risk simultaneously, the system escalates to high — because overlapping risks compound.

### 🔍 Configurable Governance
- Full CRUD API for policy profiles (`/api/policies`)
- Policy editor UI in the dashboard
- Complete audit trail for every decision
- Per-use-case, per-region policy configuration

---

## Business Proposal & Core Product Features (The ControlPlane Dashboard)

ControlPlane.ai offers a complete UI/UX observability suite tailored for enterprise compliance officers, AI engineers, and product managers. The platform is driven by four core dashboard modules designed to give your business total control over GenAI usage:

### 1. Dashboard (Real-time Observability & Review)
The Dashboard serves as the mission control for your AI ecosystem.
- **Live Traffic Feed:** A Server-Sent Events (SSE) feed streams all AI requests in real-time, displaying cost, latency, risk vectors, and the action taken (Pass, Block, Escalate).
- **Human Review Queue:** Any request flagged for escalation lands here. Human reviewers can inspect the prompt, the AI's intended response, and choose to "Approve" (release the response) or "Block" it. This builds a continuous human-in-the-loop feedback cycle and protects users from edge-case failures.

### 2. Policies (Dynamic Governance)
Different AI applications require different levels of strictness. The Policies module allows you to define configurable governance thresholds without writing a single line of code.
- **Multi-tenant Profiles:** Define strict rules for your public-facing *Customer Support Bot* while allowing more permissive thresholds for your internal *Analytics Pipeline*.
- **3-Dimensional Tuning:** Adjust sensitivity across three axes: **Performance** (hallucinations, refusal), **Cost** (token limits, cache), and **Responsibility** (toxicity, data leakage, PII).
- **Per-Region & Industry Configuration:** Readily adapt to different regulatory expectations (e.g. EU vs US data protection) by applying different policy profiles based on geography and use case.
- **Instant Deployment:** Edits to policies are applied to the proxy immediately, protecting future requests without requiring a system restart or engineering deployment.

### 3. Analytics (System Trust & Tuning)
The Analytics engine translates operational metadata into actionable business intelligence.
- **System Trust Score:** A high-level metric (0-100%) grading the reliability of your AI firewall, automatically penalized by false positives and false negatives. 
- **Detection Performance Table:** Granular, per-check accuracy metrics. Easily identify if your `jailbreak_filter` is causing too many False Positives, allowing you to loosen that specific policy threshold.
- **App-Specific Latency Tracking:** Monitor the average latency overhead introduced by the proxy for each specific application profile, ensuring SLAs are maintained.

### 4. Compliance (Audit & Ledger)
Designed for legal, security, and compliance teams to ensure strict regulatory adherence.
- **Recent Activity Ledger:** An immutable, chronological ledger of all AI requests, their risk scores, and the final action taken.
- **Human Override Tracking:** Explicitly tracks when a human reviewer overrides an AI decision (e.g., approving a blocked request), providing complete traceability for audits.
- **App-Level Statistics:** Real-time visibility into the Total Requests, Block Rates, and Override Rates broken down by individual application profiles.

---

## 3-Dimension Risk Model

| Dimension | What It Catches | Checks |
|:---|:---|:---|
| **Performance** | AI being wrong | Confidence analysis, hallucination detection, refusal detection, LLM-as-judge |
| **Cost** | AI being wasteful | Token budget, cost anomaly, duplicate/waste detection, cache hit rate |
| **Responsibility** | AI being harmful | PII detection, toxicity screening, bias detection, data leakage |

---

## Quick Start

### Prerequisites
- Python 3.10+
- pip

### Setup
```bash
# Clone the repository
git clone https://github.com/Parth7234/aic.git
cd aic

# Install dependencies
pip install -r requirements.txt

# Start the server (mock mode — no API key needed)
python -m controlplane.main
```

The server starts at `http://localhost:8000` with:
- **Dashboard:** `http://localhost:8000/` (real-time observability UI)
- **API Proxy:** `http://localhost:8000/v1/chat/completions` (OpenAI-compatible)
- **REST API:** `http://localhost:8000/api/...` (stats, policies, sessions, feedback)

### Run the Demo
```bash
# In another terminal — sends realistic traffic across 3 app profiles
python -m controlplane.demo
```

The demo runs 3 phases:
1. **Traffic Simulation** — 16 requests across 3 apps with different risk scenarios
2. **Feedback Loop** — Simulates human review actions (approve, block, release)
3. **Multi-Turn Session** — 4-turn conversation demonstrating compounding risk escalation

### Live Mode (optional)
```bash
# Set your OpenAI API key for live LLM proxying
export OPENAI_API_KEY="sk-..."
export CONTROLPLANE_MODE="live"
python -m controlplane.main
```

### Testing
We have added a suite of standalone test scripts to verify the core logic without spinning up the full API:
```bash
# Verify policy overrides and threshold configurations
python test_policies.py

# Verify the Server-Sent Events (SSE) broadcasting logic
python test_sse.py

# Verify the database schema and query functionality
python controlplane/test_db.py
```

---

## API Reference

### Proxy (OpenAI-compatible)
| Method | Endpoint | Description |
|:---|:---|:---|
| POST | `/v1/chat/completions` | Proxied chat completion with ControlPlane checks |

### Dashboard & Stats
| Method | Endpoint | Description |
|:---|:---|:---|
| GET | `/api/stats` | Aggregate statistics (filterable by app) |
| GET | `/api/requests` | Paginated request list |
| GET | `/api/requests/{id}` | Full request detail with all checks |

### Policy Management
| Method | Endpoint | Description |
|:---|:---|:---|
| GET | `/api/policies` | List all active policies |
| POST | `/api/policies` | Create a new policy profile |
| PUT | `/api/policies/{id}` | Update a policy |
| DELETE | `/api/policies/{id}` | Soft-delete a policy |

### Feedback & Metrics
| Method | Endpoint | Description |
|:---|:---|:---|
| POST | `/api/requests/{id}/action` | Human review action (approve/block/release) |
| GET | `/api/feedback/stats` | Aggregated FP/FN rates, override rate, per-check accuracy |
| GET | `/api/feedback` | Recent human overrides |

### Sessions
| Method | Endpoint | Description |
|:---|:---|:---|
| GET | `/api/sessions` | Active sessions with cumulative risk |
| GET | `/api/sessions/{id}` | Session detail with all associated requests |

### Audit & Governance
| Method | Endpoint | Description |
|:---|:---|:---|
| GET | `/api/audit-log` | Audit trail (filterable by policy, event type) |

---

## Tech Stack

- **Backend:** Python, FastAPI, Uvicorn
- **Database:** SQLite (WAL mode for concurrent reads)
- **Frontend:** Vanilla HTML/CSS/JS, Chart.js, Server-Sent Events
- **LLM Integration:** OpenAI-compatible API (mock mode included)

---

## Project Structure

```
aic/
├── controlplane/
│   ├── main.py              # FastAPI server entry point
│   ├── proxy.py             # 2-Gate pipeline (core proxy handler)
│   ├── policy.py            # Policy engine (multi-tenant, cross-dimensional)
│   ├── config.py            # Configuration & policy profiles
│   ├── database.py          # SQLite storage (requests, checks, sessions, feedback)
│   ├── api.py               # REST API endpoints
│   ├── demo.py              # Traffic simulator (3 phases)
│   ├── test_db.py           # Standalone DB unit tests
│   ├── checkers/
│   │   ├── gate1.py         # Pre-inference: cache, jailbreak, PII redaction
│   │   ├── performance.py   # Confidence, hallucination, LLM-as-judge
│   │   ├── cost.py          # Token budget, cost anomaly, waste detection
│   │   └── responsibility.py # PII, toxicity, bias, data leakage
│   └── dashboard/
│       ├── index.html        # Real-time observability dashboard
│       ├── app.js            # Dashboard logic + SSE handler
│       └── style.css         # Dashboard styling
├── test_policies.py          # Core policy logic tests
├── test_sse.py               # Server-Sent Events tests
├── requirements.txt
└── README.md
```

---

## Design Assumptions

1. **Enterprise multi-tenant:** Three distinct app profiles with different risk tolerances operate simultaneously.
2. **Data Source Diversity:** Assumes a mix of well-governed and loosely-governed internal data sources feeding the AI, making rigorous output screening essential.
3. **Scale:** Designed for tens of thousands of interactions per week (SQLite WAL mode handles concurrent reads).
4. **Input/output layer:** Works at the API boundary (not model internals), compatible with any OpenAI-compatible provider.
5. **Mock-first:** Full demonstration without API keys — all detection patterns work in mock mode.
6. **Feedback-driven:** Human overrides flow back as false positive/negative signals to measure and tune detection quality.
