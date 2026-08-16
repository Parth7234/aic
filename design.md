# ControlPlane.ai — Dashboard Design Brief

> **For:** Design agent / UI developer upgrading the dashboard  
> **Product:** Real-time AI observability & guardrails monitoring tool  
> **Current state:** Functional prototype with basic dark theme  

---

## 1. Product Context

**ControlPlane.ai** is a proxy layer that sits between apps and LLM providers, monitoring every AI response across three dimensions:

| Dimension | Color | What It Catches |
|:---|:---|:---|
| **Performance** | `#6366f1` (Indigo) | Hallucinations, confidently wrong answers, excessive refusals |
| **Cost** | `#06b6d4` (Cyan) | Token waste, budget overruns, duplicate queries, cost anomalies |
| **Responsibility** | `#f59e0b` (Amber) | PII leakage, toxic content, bias, data/system-prompt exposure |

**Target user:** Engineering leads, AI platform teams, compliance officers at enterprises running LLM-powered products. They glance at this dashboard 50+ times a day — it needs to be information-dense but scannable.

---

## 2. Current Architecture (DO NOT change)

### Tech Stack
- **HTML + Vanilla CSS + Vanilla JS** (no frameworks, no build step)
- **Chart.js 4.4.7** via CDN for all charts
- **Google Fonts:** Inter (UI text), JetBrains Mono (data/code)
- **SSE (Server-Sent Events)** for real-time updates
- Served as static files by FastAPI at `/dashboard/*`

### Files You Will Edit
```
controlplane/dashboard/
├── index.html    ← Structure & layout
├── style.css     ← All styling (902 lines currently)
└── app.js        ← Client logic, chart config, DOM rendering (690 lines)
```

### Files You Must NOT Edit
Everything outside `controlplane/dashboard/` — the backend, API, proxy, checkers, etc. The dashboard is purely a frontend consumer of the API.

---

## 3. API Contract (Data Sources)

The dashboard consumes these endpoints. **The response shapes are fixed — do not assume new fields.**

### `GET /api/stats` → Summary metrics for gauges/charts
```json
{
  "total_requests": 13,
  "risk_distribution": { "low": 5, "medium": 2, "high": 6 },
  "action_distribution": { "pass": 5, "block": 4, "escalate": 3, "edit": 1 },
  "dimension_risks": {
    "performance": { "low": 37, "medium": 0, "high": 2 },
    "cost":        { "low": 45, "medium": 3, "high": 4 },
    "responsibility": { "low": 47, "medium": 1, "high": 4 }
  },
  "total_cost_usd": 1.163578,
  "avg_cost_usd": 0.089506,
  "avg_latency_ms": 2353.85,
  "cost_trend": [
    { "timestamp": "2026-08-15T10:27:35Z", "cost": 0.00447 },
    ...
  ],
  "top_flags": [
    { "check_name": "toxicity_screening", "dimension": "responsibility", "count": 3 },
    { "check_name": "token_budget", "dimension": "cost", "count": 2 },
    ...
  ]
}
```

### `GET /api/requests?limit=50&offset=0&risk=high` → Feed items
```json
{
  "requests": [{
    "id": "uuid",
    "timestamp": "ISO-8601",
    "model": "gpt-4o",
    "prompt": "full prompt text",
    "response": "full original response",
    "input_tokens": 45,
    "output_tokens": 52,
    "cost_usd": 0.00447,
    "latency_ms": 820.0,
    "overall_risk": "low" | "medium" | "high",
    "action_taken": "pass" | "flag" | "edit" | "block" | "escalate",
    "edited_response": "modified response text or null",
    "metadata": "JSON string with modifications array"
  }]
}
```

### `GET /api/requests/{id}` → Full detail with check results
Same as above, plus:
```json
{
  "checks": [{
    "id": "uuid",
    "request_id": "parent-uuid",
    "dimension": "performance" | "cost" | "responsibility",
    "check_name": "confidence_analysis" | "pii_detection" | "token_budget" | ...,
    "score": 0.0 to 1.0,
    "risk_level": "low" | "medium" | "high",
    "details": "JSON string with check-specific data",
    "is_sync": 0 | 1,
    "timestamp": "ISO-8601"
  }]
}
```

### `GET /api/stream` → SSE real-time events
Event types:
- `new_request` — new AI interaction processed (same fields as feed item)
- `async_checks_complete` — background checks finished for a request
- `human_action` — reviewer approved/blocked an escalated request
- `ping` — keepalive every 30s

### `POST /api/requests/{id}/action` → Human review
Body: `{ "action": "approve" | "block" }`

---

## 4. Current UI Layout

```
┌──────────────────────────────────────────────────────────────────┐
│  [Logo] ControlPlane.ai    [MOCK MODE] ●Connected    [▶ Simulate]│
├──────────┬──────────────────────────────────┬────────────────────┤
│ SIDEBAR  │         LIVE FEED                │   DETAIL PANEL     │
│ 300px    │         flex-1                   │   340px            │
│          │                                  │                    │
│ [Stats]  │  [Filter: All|High|Med|Low]      │  Request Detail    │
│ 3 cards  │                                  │  - Meta (id,model) │
│          │  ┌─ Feed Item ─────────────┐     │  - Risk badge      │
│ [Gauges] │  │ gpt-4o          16:22   │     │  - Action badge    │
│ 3 rings  │  │ → prompt preview...     │     │  - Cost/tokens     │
│ Perf     │  │ response preview...     │     │  - Prompt text     │
│ Cost     │  │ [HIGH] [block] $0.0045  │     │  - Response text   │
│ Resp     │  └─────────────────────────┘     │  - Edited response │
│          │  ┌─ Feed Item ─────────────┐     │  - Check Results:  │
│ [Charts] │  │ gpt-4o-mini     16:22   │     │    ┌─────────────┐ │
│ Cost     │  │ → prompt preview...     │     │    │ [perf] 0%   │ │
│ trend    │  │ response preview...     │     │    │ ████░░ bar  │ │
│ (line)   │  │ [LOW] [pass] $0.0001   │     │    │ details...  │ │
│          │  └─────────────────────────┘     │    └─────────────┘ │
│ Risk     │                                  │                    │
│ dist     │         ... more items           │  [✓ Approve]       │
│ (donut)  │                                  │  [✕ Block]         │
│          │                                  │  (if escalated)    │
│ Top      │                                  │                    │
│ flags    │                                  │                    │
│ (h-bar)  │                                  │                    │
└──────────┴──────────────────────────────────┴────────────────────┘
```

---

## 5. Current Design Tokens (CSS Variables)

```css
/* Base */
--bg-primary: #0a0a0f;
--bg-secondary: #12121a;
--bg-card: #16161f;
--bg-card-hover: #1c1c28;

/* Text */
--text-primary: #f0f0f5;
--text-secondary: #9898a8;
--text-muted: #6b6b7b;

/* Accents */
--accent-indigo: #6366f1;
--accent-cyan: #06b6d4;
--accent-gradient: linear-gradient(135deg, #6366f1, #06b6d4);

/* Risk (semantic — keep these consistent) */
--risk-low: #22c55e;    /* Green */
--risk-medium: #f59e0b; /* Amber */
--risk-high: #ef4444;   /* Red */

/* Actions */
--action-pass: #22c55e;
--action-flag: #f59e0b;
--action-edit: #3b82f6;
--action-block: #ef4444;
--action-escalate: #a855f7;
```

---

## 6. Component Inventory

### Current Components (ID references in app.js)

| Component | HTML IDs | JS Functions | Description |
|:---|:---|:---|:---|
| **Top Bar** | `modeBadge`, `statusDot`, `statusText`, `simulateBtn` | `simulateTraffic()` | Logo, connection status, simulate button |
| **Stat Cards** | `totalRequests`, `totalCost`, `avgLatency` | `updateStats()` | 3 summary cards in sidebar |
| **Gauges** | `gaugePerfRing/Value/Sub`, `gaugeCostRing/Value/Sub`, `gaugeRespRing/Value/Sub` | `updateGauge()` | 3 SVG ring gauges (one per dimension) |
| **Cost Chart** | `costChart` canvas | `initCharts()`, `updateCostChart()` | Line chart, Chart.js |
| **Risk Chart** | `riskChart` canvas | `updateRiskChart()` | Doughnut chart, Chart.js |
| **Flags Chart** | `flagsChart` canvas | `updateFlagsChart()` | Horizontal bar chart, Chart.js |
| **Feed** | `feedList`, `feedEmpty` | `addFeedItem()`, `createFeedElement()`, `setFilter()` | Scrolling list with filter tabs |
| **Detail Panel** | `detailPlaceholder`, `detailContent`, `detailMeta`, `detailBody` | `selectRequest()`, `renderDetail()`, `closeDetail()` | Right panel with full request view |
| **Review Buttons** | inline in `renderDetail()` | `humanAction()` | Approve/Block for escalated items |

### Dynamic CSS Classes Used in JS
```
feed-item, risk-high, risk-medium, risk-low, selected
flash-red, flash-amber
feed-badge, action-pass, action-flag, action-edit, action-block, action-escalate
filter-btn, active
check-card, check-card-bar-fill
review-btn, approve, block
btn-primary, loading
```

> **⚠️ WARNING:** If you rename any CSS class used in `app.js`, you MUST update `app.js` too. Search for the class name in `app.js` before renaming.

---

## 7. Animations Currently Used

| Animation | Where | CSS |
|:---|:---|:---|
| `slideIn` | New feed items | `translateY(-8px)` → `translateY(0)`, 300ms |
| `flashRed` | High-risk items | Red box-shadow pulse, 1.5s |
| `flashAmber` | Medium-risk items | Amber box-shadow pulse, 1.5s |
| `pulse-dot` | Connection status dot | Opacity pulse, 2s infinite |
| `spin` | Simulate button loading | 360° rotation |
| Gauge ring fill | SVG stroke-dashoffset | 1s cubic-bezier transition |

---

## 8. Design Upgrade Goals

### Must Have
- [ ] More polished, premium feel — the current UI is functional but flat
- [ ] Better visual hierarchy — important data should pop, secondary data should recede
- [ ] Improved glassmorphism effects — the top bar has it but the rest doesn't use it
- [ ] Better empty states — the current "No AI traffic" state is bland
- [ ] Improved check result cards in the detail panel — they're too plain
- [ ] More dramatic risk color coding — high risk items should feel urgent
- [ ] Better mobile/responsive handling — currently the detail panel just disappears on mobile

### Nice to Have
- [ ] Animated counter transitions when stat values change (counting up/down effect)
- [ ] Skeleton loading states for feed items and charts
- [ ] A subtle animated background pattern or gradient mesh
- [ ] Tooltip/popover on gauge rings showing breakdown details
- [ ] A "timeline" or "waterfall" view for check results (sync vs async timing)
- [ ] Toast notifications when high-risk items arrive
- [ ] Smooth scroll-to-top when new items arrive in the feed
- [ ] Particle or glow effects on the logo
- [ ] Subtle animated grid/dot pattern in the background

### Do NOT Change
- The 3-column layout structure (sidebar | feed | detail)
- The three risk levels (low/medium/high) and their semantic colors (green/amber/red)
- The five action types (pass/flag/edit/block/escalate)
- The SSE-based real-time update mechanism
- The Chart.js library (don't switch to D3 or anything else)
- Any HTML element IDs used by `app.js` (see Component Inventory above)
- The API endpoints or their response shapes

---

## 9. Design Inspiration

The dashboard should feel like a premium DevOps/security monitoring tool. Think:
- **Linear** — clean typography, subtle borders, smooth transitions
- **Vercel Dashboard** — minimal, information-dense, dark mode done right
- **Datadog** — rich data visualization with clear risk indicators
- **Raycast** — polished glassmorphism, smooth micro-interactions
- **GitHub Copilot Dashboard** — AI-specific monitoring with clean cards

Key aesthetic principles:
1. **Information density over decoration** — every pixel should convey useful data
2. **Urgency through color, not size** — high risk = red glow/border, not bigger cards
3. **Depth through layering** — use glass, shadows, and subtle borders to create visual hierarchy
4. **Motion as feedback** — animations should confirm actions, not distract

---

## 10. Running the Dashboard

```bash
# Start the backend server (must be running for the dashboard to work)
cd /Users/parthsingla/Coding/Project/aic
python3 -m controlplane.main

# Dashboard is at: http://localhost:8000/
# Click "Simulate Traffic" to populate with demo data

# Or run the CLI demo for 13 varied scenarios:
python3 -m controlplane.demo
```

The dashboard auto-connects via SSE and loads existing data on page load. All changes to `index.html`, `style.css`, or `app.js` are served immediately (no build step needed, but server restart required for Python changes).
