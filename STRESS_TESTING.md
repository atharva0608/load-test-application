# StressForge v3.0 — Production-Grade Load Testing & Observability Platform

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     StressForge v3.0 Stack                      │
├──────────┬──────────┬──────────┬──────────┬──────────┬──────────┤
│ Frontend │ Backend  │ Worker   │ Beat     │ Postgres │ Redis    │
│ Nginx    │ FastAPI  │ Celery   │ Celery   │ 15.x    │ 7.x     │
│ :3001    │ :8000    │ 8 conc.  │ 10s tick │ :5432   │ :6379   │
├──────────┴──────────┴──────────┴──────────┴──────────┴──────────┤
│ Locust Load Generator (:8089)                                   │
└─────────────────────────────────────────────────────────────────┘
```

## What's New in v3.0

### Backend — 15 New API Endpoints

| Category | Endpoint | Method | Description |
|----------|----------|--------|-------------|
| **Stress** | `/api/stress/degradation` | POST | Graceful degradation test with DB slowness |
| **Stress** | `/api/stress/pool-exhaust` | POST | Connection pool exhaustion scenario |
| **Stress** | `/api/stress/tenants/{id}/stress` | POST | Tenant-scoped load with SLA tier awareness |
| **Metrics** | `/api/metrics/db-pool` | GET | Live SQLAlchemy pool status |
| **Metrics** | `/api/metrics/pod-age` | GET | Pod uptime + cache hit rate |
| **Metrics** | `/api/metrics/latency-percentiles` | GET | p50/p95/p99/p99.9 per endpoint |
| **Metrics** | `/api/metrics/cost-estimate` | GET | AWS cost simulation |
| **Metrics** | `/api/metrics/slow-requests` | GET | Requests exceeding 1000ms |
| **Baseline** | `/api/baseline/record` | POST | Capture golden latency baseline |
| **Baseline** | `/api/baseline/compare` | POST | Compare against baseline (regression check) |
| **Baseline** | `/api/baseline/report` | GET | CI-compatible pass/fail report |
| **Admin** | `/api/admin/seed` | POST | Bulk seed 100K–10M products |
| **Stream** | `/api/stream` | GET | SSE telemetry stream (1Hz) |
| **Chaos** | `/api/chaos/inject` | POST | Inject failure (redis/db/app) |
| **Chaos** | `/api/chaos/clear` | DELETE | Clear all active chaos |

### Middleware Pipeline (Every Request)

1. **Request ID + Timing** → `X-Request-ID`, `X-Response-Time` headers
2. **Latency Recording** → Per-endpoint in-memory histogram for percentile tracking
3. **Cost Event** → Records CPU seconds, IOPS, data transfer for cost simulation
4. **SSE Recording** → Feeds RPS/error rate to live dashboard stream
5. **Slow Request Logger** → Requests >1000ms logged to inspector feed + SSE event

### Dashboard — 8-Tab Live Monitoring

| Tab | Charts | Data Source |
|-----|--------|-------------|
| **Overview** | Load Curve + RPS, Latency Percentiles, Error Rate, Throughput | SSE |
| **Infrastructure** | CPU/pod, Memory/pod, HPA step chart, DB Pool gauge | SSE |
| **Latency** | Heatmap, Per-endpoint table, Slow request feed, Histogram | SSE + API poll |
| **Queue** | Queue depth, Worker throughput, Task duration, DLQ feed | SSE + API poll |
| **Scenarios** | Builder with preview curve, Active status, History table | API |
| **Uptime & SLA** | Status banner, 90-day bar, SLA tiles, Incidents, Endpoint matrix | API poll |
| **Chaos** | Injection panel, Recovery timeline, Chaos log, Circuit breakers | API poll |
| **Cost** | Live ticker, Donut breakdown, Cost vs Load scatter, Suggestions | SSE + API poll |

### Always-Visible Elements

- **6 KPI Tiles**: RPS, Throughput, P99 Latency, Error Rate, Active Users, Replicas
  - Each with sparkline (60s history) and delta arrow
  - Color-coded: green/yellow/red based on thresholds
- **Event Log**: Color-coded feed (blue=info, yellow=warning, red=error, green=recovery)
  - Auto-scrolls, pauses when user scrolls up
  - Populated from SSE events stream

### Locust Personas (11 Total)

| # | Persona | Weight | What It Tests |
|---|---------|--------|---------------|
| 1 | BrowsingUser | 5 | Catalog reads, search, pagination |
| 2 | ShoppingUser | 3 | Full purchase flow: register → browse → order |
| 3 | APIGatewayUser | 3 | Authenticated API traffic patterns |
| 4 | MobileClientUser | 2 | Short sessions, slow network simulation |
| 5 | BatchJobUser | 2 | Bulk orders, ETL-style workloads |
| 6 | AdminUser | 1 | Stats, aggregates, monitoring endpoints |
| 7 | StressUser | 2 | CPU/Memory/IO stress + queue bursts |
| 8 | AbusiveUser | 1 | Rate limits, SQLi, IP spoofing, bcrypt stress |
| 9 | DeepPaginationUser | 1 | Page 500+ OFFSET regression testing |
| 10 | ColdStartUser | 1 | HPA scale-out + cache warm-up measurement |
| 11 | TenantUser | 1 | Multi-tenant noisy neighbor isolation |

### Traffic Shapes (5 Modes)

| Shape | Pattern | Tests |
|-------|---------|-------|
| **Spike** | 10 → 100 → 10 users | Autoscaler reaction time |
| **Soak** | Steady 30 users for hours | Memory leaks, connection drift |
| **Burst** | 50 on / 50 off cycles | Cold start recovery |
| **Ramp** | Linear 0 → 200 users | Breaking point discovery |
| **Flash Crowd** | Exponential growth | Thundering herd behavior |

## New Feature Details

### Multi-Tenant Load Isolation (Requirement 1)

Each tenant is assigned an SLA tier affecting resource quotas:

| Tier | Rate Limit | Priority Queue | Max Intensity |
|------|-----------|----------------|---------------|
| FREE | 10 req/s | `low_priority` | 20 |
| PRO | 100 req/s | `medium_priority` | 60 |
| ENTERPRISE | 1000 req/s | `high_priority` | 100 |

```bash
# Test noisy neighbor
curl -X POST localhost:8000/api/stress/tenants/tenant-1/stress \
  -H "Content-Type: application/json" \
  -d '{"intensity": 80, "duration_seconds": 30}'
```

### Graceful Degradation (Requirement 2)

Tests whether the API returns cached stale data vs hard errors under DB slowness:

```bash
# Inject 500ms DB delay
curl -X POST localhost:8000/api/stress/degradation \
  -H "Content-Type: application/json" \
  -d '{"intensity": 50, "duration_seconds": 5}'
```

### Connection Pool Monitoring (Requirement 3)

```bash
# Check pool status
curl localhost:8000/api/metrics/db-pool
# Returns: pool_size, checked_out, overflow, checked_in, status_summary

# Exhaust pool deliberately
curl -X POST localhost:8000/api/stress/pool-exhaust \
  -H "Content-Type: application/json" \
  -d '{"intensity": 50, "duration_seconds": 5}'
```

### Latency Percentiles (Requirement 5)

```bash
# Per-endpoint p50/p95/p99/p99.9
curl localhost:8000/api/metrics/latency-percentiles

# Slow requests (>1000ms)
curl localhost:8000/api/metrics/slow-requests?limit=20
```

### Chaos Injection (Requirement 6)

```bash
# Inject Redis latency
curl -X POST "localhost:8000/api/chaos/inject?target=redis&failure_type=latency&latency_ms=500&duration_seconds=60"

# Inject memory leak
curl -X POST "localhost:8000/api/chaos/inject?target=application&failure_type=memory_leak&latency_ms=500&duration_seconds=60"

# Clear all chaos
curl -X DELETE localhost:8000/api/chaos/clear
```

### Cost Simulation (Requirement 10)

```bash
curl localhost:8000/api/metrics/cost-estimate
# Returns: cost_per_hour_usd, cost_per_month_usd, breakdown by service
```

### Regression Testing (Requirement 11)

```bash
# Record baseline after warm-up
curl -X POST localhost:8000/api/baseline/record

# Compare against baseline (fails if p99 regressed >20%)
curl -X POST localhost:8000/api/baseline/compare?threshold_percent=20

# CI-compatible report
curl localhost:8000/api/baseline/report
```

### Bulk Data Seeding (Requirement 7)

```bash
# Seed 100K products
curl -X POST localhost:8000/api/admin/seed \
  -H "Content-Type: application/json" \
  -d '{"count": 100000, "batch_size": 5000}'
```

## SSE Stream Protocol

The dashboard connects via:
```javascript
const stream = new EventSource('/api/stream');
stream.onmessage = (e) => {
    const data = JSON.parse(e.data);
    // data contains: rps, p50, p95, p99, p999, error_rate,
    // cpu_percent, ram_percent, pool_used, queue_depth,
    // replicas, cost_per_hour, events[]
};
```

Payload pushed every 1 second. No polling needed.

## Design System

| Element | Value |
|---------|-------|
| Background | `#080b10` (near-black with blue tint) |
| Cards | `#0d1417` with `rgba(0,212,255,0.08)` border |
| Info/RPS | Cyan `#00d4ff` |
| Success | Green `#00ff9d` |
| Warning | Orange `#ff6b35` |
| Error | Red `#ff3b3b` |
| Headings font | Syne |
| Metrics font | JetBrains Mono |
| Chart lines | 1.5px, no fill |
| Grid lines | `rgba(255,255,255,0.03)` |

## Deployment

```bash
docker compose up --build

# Services
# Frontend dashboard: http://localhost:3001
# Backend API:        http://localhost:8000
# API docs:           http://localhost:8000/api/docs
# SSE stream:         http://localhost:8000/api/stream
# Prometheus:         http://localhost:8000/prometheus/metrics
# Locust:             http://localhost:8089

# Quick verification
curl localhost:8000/api/health
curl localhost:8000/api/metrics/db-pool
curl localhost:8000/api/metrics/latency-percentiles
```
