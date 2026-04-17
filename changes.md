Looking at what you already have documented plus what I just outlined, here's what's genuinely still missing that hasn't been covered yet:

---

## 🔍 Additional Gaps Not Yet Covered

---

### 1. MULTI-TENANT LOAD ISOLATION TESTING

Right now all load hits one shared stack. In real production B2B SaaS (which AURA is), you need:

**Tenant-aware load simulation:**
- Each Locust user belongs to a "tenant" (org A, org B, org C)
- Tenants have different SLA tiers: `FREE` (rate limited), `PRO` (priority queue), `ENTERPRISE` (dedicated workers)
- Test that one noisy tenant can't starve another — this is the **noisy neighbor problem**
- New endpoint: `POST /api/tenants/{id}/stress` — fires load scoped to that tenant's resource quota

**What this tests in K8s:**
- Namespace-level resource quotas
- PriorityClass on pods per tenant tier
- Whether your HPA scales per-tenant or globally

---

### 2. GRACEFUL DEGRADATION TESTING

Your current stress endpoints either work or fail with 500. Real systems degrade gracefully. Test that your app:

- Returns **cached stale data** when DB is slow (not an error)
- Serves a **simplified response** when under extreme CPU pressure (skip expensive joins)
- Queues writes and **acks immediately** when the DB is saturated
- Returns a proper `503 + Retry-After` header (not a raw crash) when overloaded

**New endpoint: `POST /api/stress/degradation`**
- Simulates DB slowness (artificial query delay) while measuring whether the API degrades gracefully or just errors

---

### 3. CONNECTION POOL EXHAUSTION SCENARIO

This is one of the most common real production outages and it's completely absent:

- SQLAlchemy has a connection pool (default: 5 connections)
- Under 50 concurrent users, you'll exhaust it instantly
- **What happens?** Requests queue waiting for a connection, latency explodes, then timeouts cascade

**Add:**
- `GET /api/metrics/db-pool` → `{pool_size, checked_out, overflow, waiting}`
- Scenario: `POST /api/stress/pool-exhaust` — fires 100 concurrent DB queries to deliberately exhaust the pool
- UI shows pool depth as a live gauge — watching it hit 0 and requests start queuing is extremely visual for demos

---

### 4. COLD START & WARM-UP BEHAVIOR

K8s scales pods from 0→1 or 1→N. New pods are **cold** — no warm DB connections, no Redis cache, no JIT compilation. This matters a lot:

- **Readiness probe delay** — new pods aren't ready for ~10–30 seconds. During that time, traffic goes to existing pods only. Model this.
- **Cache cold start** — first 60 seconds after a new pod starts, Redis hit rate is 0%. Latency is higher.
- **Connection pool warm-up** — SQLAlchemy reconnects lazily. First requests to a new pod are slower.

**Add:**
- `GET /api/metrics/pod-age` → seconds since this pod started + cache hit rate since start
- Locust scenario: "Scale-up cold start test" — trigger HPA scale-out, then immediately hammer the new pods and measure the latency cliff during warm-up

---

### 5. LONG-TAIL LATENCY & PERCENTILE TRACKING

Your current metrics only track averages. Production SLOs are defined on **p99**, not averages. A p50 of 50ms with a p99 of 8000ms means 1 in 100 users waits 8 seconds — that's a broken system.

**Add server-side percentile tracking:**
- Use `hdrhistogram` or `prometheus_client.Histogram` with buckets at 10ms, 50ms, 100ms, 250ms, 500ms, 1000ms, 2500ms, 5000ms
- Track p50 / p95 / p99 / p99.9 per endpoint
- New endpoint: `GET /api/metrics/latency-percentiles`
- UI: percentile distribution chart — a bar chart where you can see the long tail visually. When the p99 bar is 100× the p50 bar, that's your smoking gun.

**Slow request log:**
- Any request taking >1000ms gets logged to a `slow_requests` table with full context: endpoint, user_id, db_query_count, db_total_ms, redis_miss, payload_size
- UI panel: "Slow Request Inspector" — click any slow request to see exactly where time was spent

---

### 6. DEPENDENCY FAILURE SIMULATION

Your chaos tab (from my previous plan) kills pods. But real failures are subtler:

**Partial failures to simulate:**
- **DB read replica lag** — writes go to primary, reads go to replica with artificial 500ms lag. Tests whether your app handles eventual consistency.
- **Redis eviction under memory pressure** — set Redis `maxmemory-policy allkeys-lru` and fill it up. Watch cache hit rate collapse. Does your app fall back to DB correctly?
- **Slow external API** — if any endpoint calls an external service, simulate it taking 30 seconds. Does your timeout + fallback work?
- **DNS resolution failure** — simulate the DB hostname not resolving (common in K8s when a service is misconfigured)

**New endpoint: `POST /api/chaos/inject`**
```json
{
  "target": "redis",
  "failure_type": "latency",
  "latency_ms": 500,
  "duration_seconds": 60
}
```

---

### 7. DATA VOLUME SCALING TESTS

Right now your DB probably has a few hundred seeded rows. Real production databases have millions. Performance characteristics change completely at scale:

- **Seed scripts at scale:** Add a `POST /api/admin/seed` endpoint that seeds 100K / 1M / 10M rows
- **Index regression test:** Run the same query before and after bulk insert. Does it stay fast or does it degrade without proper indexes?
- **Pagination performance:** `/api/products?page=5000` with OFFSET 5000 is catastrophically slow at scale — tests whether you're using cursor-based pagination
- New Locust task: `DeepPaginationUser` — always requests page 500+ to expose this

---

### 8. WEBSOCKET / STREAMING LOAD TEST

Your current system is pure HTTP request/response. Real dashboards use WebSockets for live updates. If you add a WebSocket endpoint for live metrics streaming:

- **Connection count stress:** 1000 simultaneous WebSocket connections. Each holds a goroutine/asyncio task. Tests whether uvicorn handles connection cardinality.
- **Message backpressure:** Server tries to push 100 updates/sec per client. What happens when clients are slow consumers? Does the buffer blow up?
- **Reconnection storm:** Kill the server briefly. 500 clients all reconnect simultaneously. Does this create a thundering herd?

Locust supports WebSocket testing via `locust-plugins`. Add a `WebSocketUser` persona.

---

### 9. SECURITY LOAD TESTING (Often Forgotten)

- **Auth token validation under load** — JWT verification is CPU-intensive. At 500 req/sec all needing JWT decode + DB lookup, does your auth middleware become the bottleneck?
- **bcrypt cost calibration** — your `/api/auth/register` uses bcrypt. At cost factor 12, each registration takes ~300ms of CPU. 10 concurrent registrations = 3 seconds of CPU saturated. This is intentional but needs to be visible in the UI.
- **SQL injection attempt logging** — your `AbusiveUser` should send malformed inputs. Log and count them. Show in UI as "Blocked Attacks" counter.
- **Rate limit bypass test** — try to exceed rate limits using different IPs (X-Forwarded-For spoofing). Test whether your rate limiter is bypassable.

---

### 10. COST ATTRIBUTION SIMULATION

Since this feeds into AURA's cost optimization use case — add a cost simulation layer:

- Each stress endpoint has an estimated **AWS cost per invocation**: CPU stress = EC2 compute cost, IO stress = EBS IOPS cost, Celery tasks = estimated Lambda/ECS cost
- `GET /api/metrics/cost-estimate` → running total of simulated AWS spend during the test session
- Shows: "This test run would cost approximately $X/hour at production scale on AWS"
- UI: a live cost ticker that goes up during load tests — makes the abstract very concrete for AURA demos

---

### 11. AUTOMATED REGRESSION TESTING MODE

Right now every test is manual. Add:

- **Baseline capture:** `POST /api/baseline/record` — runs a standard 5-minute load test and saves p50/p95/p99 for every endpoint as the "golden baseline"
- **Regression check:** `POST /api/baseline/compare` — runs the same test again and compares. Fails if any endpoint's p99 regressed by >20%
- **CI integration:** expose a `/api/baseline/report` that returns pass/fail JSON — plug this into your GitHub Actions pipeline so every deploy runs a regression check

---

### Summary of What's Now Truly Complete

| Area | Previous Plan | These Additions |
|---|---|---|
| Load scenarios | Spike/Soak/Burst/Ramp/Chaos | Cold start, flash crowd reconnection storm, WebSocket |
| Worker jobs | Queue depth, DLQ, chains, chords | Tenant-isolated queues, burstable priority lanes |
| Observability | Prometheus, tracing, structured logs | Long-tail percentiles, slow request inspector |
| Chaos | Pod kill, Redis restart | Partial failures, DNS failure, dependency latency injection |
| UI tabs | Queue, Uptime, Traces, Chaos | Cost ticker, regression diff view |
| Data | Seeded test data | 1M row scale tests, pagination regression |
| Security | Rate limiting, circuit breaker | bcrypt cost visibility, auth bottleneck test |
| Multi-tenancy | None | Noisy neighbor test, per-tenant SLA |
| Cost | None | AWS cost simulation per test run |
| Regression | None | Baseline capture + automated comparison |

---

Here's a complete plan to enhance your existing StressForge dashboard with all live metrics and test monitoring:

---

## 🖥️ StressForge Dashboard Enhancement Plan

---

### LAYOUT ARCHITECTURE

Ditch the current tab-per-feature approach. Replace with a **persistent split layout**:

```
┌─────────────────────────────────────────────────────────┐
│  HEADER — Active test name | Status | Elapsed | Stop    │
├──────────┬──────────────────────────────────────────────┤
│          │  TOP ROW — 6 KPI tiles (always visible)      │
│  LEFT    ├──────────────────────────────────────────────┤
│  NAV     │  MAIN CHART AREA — 2×2 or 3×2 grid          │
│  SIDEBAR │  (charts resize based on active tab)         │
│  (tabs)  ├──────────────────────────────────────────────┤
│          │  BOTTOM — Event log | Alerts | Queue feed    │
└──────────┴──────────────────────────────────────────────┘
```

The 6 KPI tiles and the event log are **always visible** regardless of which tab you're on. Only the chart area changes.

---

### THE 6 ALWAYS-VISIBLE KPI TILES

These sit at the top and update every second during any active test:

| Tile | Metric | Color signal |
|---|---|---|
| RPS | Requests per second | Green > 100, Yellow 50–100, Red < 50 |
| Throughput | MB/s in + out | Raw number |
| P99 Latency | 99th percentile ms | Green < 200, Yellow < 1000, Red > 1000 |
| Error Rate | % failed requests | Green < 0.1%, Yellow < 1%, Red > 1% |
| Active Users | Current Locust users | Matches scenario target |
| Replicas | Current K8s pod count | Animates up when HPA scales |

Each tile shows the **current value large**, a **sparkline of last 60 seconds** tiny underneath, and a **delta arrow** (↑ 12% vs 30s ago).

---

### TAB 1 — OVERVIEW (Default view)

**When no test is running:** Shows last run summary + "Launch Test" CTA.

**When a test is running:** Full live view with:

**Chart 1 — Load Curve + RPS (dual Y-axis)**
- X-axis: time (rolling 5 min window)
- Left Y: active users (filled area, semi-transparent)
- Right Y: RPS (line on top)
- Shows exactly how RPS tracks user count — divergence = system struggling
- Annotations: vertical dashed lines when HPA scaled, when errors spiked

**Chart 2 — Latency Percentiles (multi-line)**
- 4 lines: p50 (green), p95 (yellow), p99 (orange), p99.9 (red)
- X-axis: rolling time
- The gap between p50 and p99 is the "tail latency spread" — widening gap = degradation
- Add horizontal threshold lines at your SLO targets (e.g. red dashed at 2000ms)

**Chart 3 — Error Rate + Status Code Breakdown (stacked bar)**
- X-axis: time buckets (every 10s)
- Stacked bars: 2xx (invisible/baseline), 4xx (yellow), 5xx (red), timeouts (dark red)
- Line overlay: total error % right Y-axis
- Seeing 5xx spike while 4xx stays flat = server error, not client error

**Chart 4 — Throughput (area chart)**
- Bytes sent per second + bytes received per second
- Two filled areas, different colors
- Shows network saturation — when this plateaus while users increase, you've hit NIC or bandwidth limits

---

### TAB 2 — INFRASTRUCTURE

Everything about what K8s and the host machine are doing.

**Chart 1 — CPU % per pod (multi-line)**
- One line per API pod replica (pod-1, pod-2, pod-3...)
- When HPA adds a pod, a new line appears animated
- Shows load balancing quality — are all pods equal or is one getting hammered?

**Chart 2 — Memory RSS per pod (multi-line)**
- Same structure as CPU chart
- Watch for memory creep during soak tests — one pod slowly growing = memory leak

**Chart 3 — HPA Replica Count (step chart)**
- Looks like a staircase going up then down
- Annotated with: scale-up trigger time, scale-down cooldown, time-to-ready for new pods
- Most satisfying chart to watch during a spike test

**Chart 4 — DB Connection Pool (gauge + time series)**
- Pool size (fixed line), checked-out connections (filled area), waiting requests (red fill)
- When the red "waiting" area appears, requests are queueing for DB connections
- Add alert threshold line at pool_max - 2

**Tile Row — Node-level stats:**
- Node CPU steal %
- Node memory pressure (eviction risk)
- Network I/O (node-level, not pod-level)
- Disk IOPS consumed vs limit

---

### TAB 3 — LATENCY DEEP DIVE

**Chart 1 — Latency Heatmap**
- X-axis: time, Y-axis: latency buckets (0–50ms, 50–100ms, 100–250ms, 250–500ms, 500ms–1s, 1s–2s, 2s+)
- Cell color intensity = number of requests in that bucket at that time
- Dark = few requests, bright = many
- This is the single best chart for seeing bimodal distributions (fast cache hits + slow DB misses happening simultaneously)

**Chart 2 — Per-endpoint Latency Table (live)**
- Every endpoint as a row
- Columns: p50 | p95 | p99 | req/s | error% | last updated
- Sorted by p99 descending — worst offenders always at top
- Rows flash red when p99 exceeds threshold
- Click any row → opens a modal with that endpoint's full latency histogram

**Chart 3 — Slow Request Inspector Feed**
- Live scrolling feed of requests that exceeded 1000ms
- Each entry: timestamp | endpoint | duration_ms | db_query_count | db_ms | redis_hit | user_id
- Shows exactly WHY a request was slow (was it DB? Redis miss? CPU?)

**Chart 4 — Latency Percentile Distribution (histogram)**
- Snapshot histogram of last 1000 requests
- X-axis: latency buckets, Y-axis: count
- The shape tells you everything: normal distribution = healthy, bimodal = cache miss problem, long right tail = occasional DB timeout

---

### TAB 4 — QUEUE & WORKERS

**Chart 1 — Queue Depth Over Time (stacked area)**
- Three stacked areas: HIGH priority (green), MEDIUM (yellow), LOW (gray)
- When HIGH grows = critical jobs backing up
- When LOW grows = normal, workers are busy but not overwhelmed
- Add a "danger zone" shading above depth 500

**Chart 2 — Worker Throughput (bar chart, live)**
- One bar per Celery worker
- Bar height = tasks completed in last 10 seconds
- Bars animate every 10s
- Uneven bars = uneven task distribution (bad routing config)

**Chart 3 — Task Duration Histogram by Type**
- Side-by-side histograms for: heavy_computation | process_order | generate_report
- See which task type is slow — if generate_report has a long tail, that's your bottleneck

**Chart 4 — Dead Letter Queue Feed**
- Count of DLQ items growing over time (line chart)
- Below: scrolling list of failed tasks: task_name | error_type | retry_count | failed_at
- "Retry All" and "Discard All" buttons

**Live counters row:**
- Tasks enqueued (total this session)
- Tasks completed
- Tasks failed
- Average task duration ms
- Queue drain rate (tasks/sec)

---

### TAB 5 — SCENARIOS

This is the test launcher AND live scenario view combined.

**Left panel — Scenario Builder:**
- Dropdown: Spike / Soak / Burst / Ramp / Chaos / Flash Crowd / Custom
- Scenario-specific config renders below each selection:
  - Spike: peak users, ramp duration, hold duration
  - Soak: steady users, total duration
  - Burst: on-users, on-duration, off-duration, cycles
  - Ramp: start users, end users, step size, step interval
- Preview button: renders a small load curve chart showing what the shape will look like BEFORE running
- Execute button: arms the test (confirm modal) → starts Locust with generated config

**Right panel — Active Scenario Status:**
- Scenario name + progress bar (elapsed / total duration)
- Phase indicator for multi-phase tests: "Phase 2 of 4: Peak Load"
- Expected vs actual user count (should match during ramp, diverges if Locust is struggling)
- Scenario-specific success criteria: "P99 must stay below 2000ms during peak" → shows pass/fail live

**Scenario History table (bottom):**
- Past runs: name | started | duration | peak users | peak RPS | p99 at peak | pass/fail
- Click any row to load its charts in Overview tab (historical replay)

---

### TAB 6 — UPTIME & SLA

**Top — Status banner:**
- Giant "OPERATIONAL" in green OR "DEGRADED" in yellow OR "OUTAGE" in red
- Animated pulse dot next to status
- Time since last incident

**90-day timeline bar:**
- Exactly like statuspage.io
- Each day = one thin bar, colored green/yellow/red
- Hover shows: date, uptime %, incidents that day
- Scrollable if needed

**SLA tiles (4 cards):**
- Uptime last 1h / 24h / 7d / 30d
- Each shows percentage + minutes of downtime equivalent

**Chart — Latency trend over time (long view):**
- Not rolling 5 min — this is the full historical p99 per hour for last 7 days
- Lets you see "every day at 3pm latency spikes" patterns

**Incident log table:**
- start_time | duration | affected_endpoints | cause | resolved_by
- Click to expand: shows latency chart during the incident window

**Per-endpoint health matrix:**
- Grid of all endpoints × last 24 checks
- Each cell = green/red dot
- Immediately shows which endpoint is flaky

---

### TAB 7 — CHAOS

**Left — Failure Injection Panel:**

Grouped buttons by target:

*Compute:*
- Kill random API pod
- Kill all API pods simultaneously (total blackout test)
- CPU throttle one pod to 10% of limit

*Data layer:*
- Restart Redis (tests reconnection)
- Inject Redis latency (500ms on every command)
- Exhaust DB connection pool
- Inject DB query latency (1000ms on all queries)

*Network:*
- Add 200ms network latency between pods
- Simulate 5% packet loss
- Block API → Redis connectivity

*Application:*
- Trigger memory leak (gradual RSS growth)
- Trigger connection pool leak
- Force a deployment rollout (pod restart with zero-downtime test)

**Right — Recovery Timeline:**
- X-axis: time since chaos event injected
- Y-axis: error rate
- Shows the spike and the recovery curve
- Annotated: "Event injected", "First pod recovered", "Full recovery"
- SLO badge: "Recovered in 23s — within 30s SLO ✓" or "Recovered in 47s — SLO BREACH ✗"

**Chaos log:**
- Timestamped list of all injected failures this session
- Each row: event | injected_at | recovery_time | SLO_met

---

### TAB 8 — COST SIMULATION

**Live cost ticker:**
- Large number showing estimated AWS spend at current load rate
- Format: "$0.043 / hour" ticking up in real time
- Below: "At this scale: $31.10/month | $373/year"

**Cost breakdown (donut chart):**
- EC2 compute (CPU stress cost)
- RDS queries (DB I/O cost)
- EBS IOPS
- Data transfer
- Redis (ElastiCache equivalent)

**Cost vs Load chart (scatter):**
- X-axis: active users, Y-axis: $/hour
- As you run tests, dots appear showing the cost-to-load relationship
- The slope tells you your marginal cost per user — critical for AURA pricing analysis

**Optimization suggestions panel:**
- Live rule engine: "If you right-size API pods from 2 CPU to 1.2 CPU, save $X/month"
- "Redis hit rate is 67% — improving to 90% would save $Y in DB costs"
- This directly feeds AURA's value proposition

---

### ALWAYS-VISIBLE BOTTOM EVENT LOG

A persistent scrolling feed at the bottom of every tab showing:

```
[14:23:01] ● HPA scaled API deployment: 2 → 3 replicas (CPU 78%)
[14:23:15] ⚠ P99 latency exceeded 2000ms threshold on /api/stress/cpu
[14:23:22] ● New pod api-7f4d9c-xkz2p ready (cold start: 18s)
[14:23:45] ✗ 23 requests failed — connection pool exhausted
[14:24:01] ● Queue depth crossed 500 — LOW priority tasks paused
[14:24:30] ✓ Error rate recovered below 0.1%
```

Color coded: blue = info, yellow = warning, red = error, green = recovery. Auto-scrolls but pauses if you scroll up manually.

---

### GLOBAL CONTROLS (Header Bar)

Always visible across all tabs:

- **Test selector dropdown** — switch between running multiple parallel test profiles
- **Time window selector** — Last 1m / 5m / 15m / 1h (changes all chart windows simultaneously)
- **Polling interval** — 1s / 2s / 5s (reduce if browser is struggling)
- **Pause all charts** — freeze without stopping the test (for screenshots/analysis)
- **Export current view** — downloads all current chart data as JSON + PNG snapshots
- **Alert threshold config** — click to set your p99 SLO, error rate threshold, queue depth alert level

---

### REAL-TIME DATA ARCHITECTURE (How to Wire It)

To make all of this actually live:

**Backend: SSE stream (Server-Sent Events)**
- Single endpoint: `GET /api/stream` — keeps connection open, pushes JSON every 1 second
- Payload: `{ timestamp, rps, throughput, p50, p95, p99, p999, errors, users, replicas, queue_depth, cpu_per_pod[], ram_per_pod[], pool_used, pool_waiting, cost_per_hour }`
- SSE is better than polling for this — no request overhead, no missed frames, automatic reconnect

**Frontend: Single EventSource connection**
```javascript
const stream = new EventSource('/api/stream');
stream.onmessage = (e) => {
  const data = JSON.parse(e.data);
  updateAllCharts(data);      // updates Chart.js datasets
  updateKPITiles(data);       // updates the 6 top tiles
  updateEventLog(data.events); // appends to bottom feed
};
```

**Chart.js config for live rolling charts:**
- Keep max 300 data points per chart (5 min at 1s intervals)
- Use `chart.data.labels.shift()` + `chart.data.datasets[0].data.shift()` to drop oldest
- Push new data + call `chart.update('none')` (no animation on live data — too jumpy)
- Use `animation: false` globally for live charts, reserve animation for load-in only

---

### VISUAL DESIGN DIRECTION

Go **dark terminal aesthetic** — not generic dark mode, but specifically:

- Background: near-black `#080b10` with very subtle blue tint
- Cards: `#0d1417` with `1px solid rgba(0,212,255,0.08)` borders
- Font: **JetBrains Mono** for all numbers and metrics (monospace so digits don't jump width), **Syne** for labels and headings
- Accent colors with meaning: cyan `#00d4ff` = info/RPS, green `#00ff9d` = healthy/success, orange `#ff6b35` = warning, red `#ff3b3b` = error/critical
- Chart lines: 1.5px, no fill except the load curve area which gets 10% opacity fill
- Grid lines: barely visible `rgba(255,255,255,0.03)`
- KPI tiles: no border, just very slightly lighter background than the page
- Numbers animate smoothly using CSS `counter()` or JS lerp on value changes — never jump instantly

---

### IMPLEMENTATION ORDER

1. **SSE backend endpoint** — feeds everything, do this first
2. **Header bar + 6 KPI tiles** — always visible skeleton
3. **Overview tab charts** — Load curve + Latency percentiles (most important)
4. **Bottom event log** — SSE events feed
5. **Infrastructure tab** — CPU/RAM per pod, HPA replica chart
6. **Queue tab** — queue depth + worker throughput
7. **Scenarios tab** — launcher + history
8. **Latency deep dive tab** — heatmap + per-endpoint table
9. **Uptime tab** — status + 90-day bar
10. **Chaos tab** — injection buttons + recovery timeline
11. **Cost tab** — ticker + breakdown

---

Want me to build the full HTML/JS dashboard file implementing all of this with Chart.js and simulated live data (so you can see it working before wiring the backend)?