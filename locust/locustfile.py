"""
StressForge — Production-Grade Locust Load Testing Scenarios.

Traffic Pattern Modes (ScenarioOrchestrator):
  - Spike Test:       normal → 10x spike → normal
  - Soak Test:        sustained moderate load for hours
  - Burst Test:       on/off cycles (cold start testing)
  - Ramp Test:        linear increase to find breaking point
  - Flash Crowd Test: exponential growth

User Personas (production-realistic):
  1. BrowsingUser     (weight=5) — Light: catalog reads, search
  2. ShoppingUser     (weight=3) — Medium: register, browse, place orders
  3. APIGatewayUser   (weight=3) — Upstream API traffic with auth
  4. MobileClientUser (weight=2) — Short sessions, slow network sim
  5. BatchJobUser     (weight=2) — Bulk orders, ETL-style loads
  6. AdminUser        (weight=1) — Stats, aggregates, reports
  7. StressUser       (weight=2) — Heavy: CPU/Memory/IO stress + queue burst
  8. AbusiveUser      (weight=1) — Rate limit testing, malformed payloads
"""
from locust import HttpUser, task, between, events, LoadTestShape
import random
import string
import json
import logging
import math
import os
import time

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════
# Helpers
# ═══════════════════════════════════════

def random_email():
    rand = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
    return f"user_{rand}@stressforge.test"


def random_username():
    rand = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    return f"sf_{rand}"


# ═══════════════════════════════════════
# Scenario Orchestrator (LoadTestShape)
# ═══════════════════════════════════════

class SpikeTestShape(LoadTestShape):
    """
    Spike Test: normal → 10x spike → normal.
    Tests autoscaler reaction time.
    Timeline: 60s@10 users → 5s ramp to 100 → 60s@100 → 5s ramp to 10 → 60s@10
    """
    stages = [
        {"duration": 60,  "users": 10, "spawn_rate": 2},
        {"duration": 65,  "users": 100, "spawn_rate": 20},
        {"duration": 125, "users": 100, "spawn_rate": 1},
        {"duration": 130, "users": 10, "spawn_rate": 20},
        {"duration": 190, "users": 10, "spawn_rate": 1},
    ]

    def tick(self):
        run_time = self.get_run_time()
        for stage in self.stages:
            if run_time < stage["duration"]:
                return (stage["users"], stage["spawn_rate"])
        return None


class SoakTestShape(LoadTestShape):
    """
    Soak Test: sustained moderate load.
    Tests memory leaks, connection pool exhaustion, DB bloat.
    """
    def tick(self):
        run_time = self.get_run_time()
        duration = int(os.getenv("SOAK_DURATION_MINUTES", "120")) * 60
        if run_time > duration:
            return None
        users = int(os.getenv("SOAK_USERS", "30"))
        return (users, 2)


class BurstTestShape(LoadTestShape):
    """
    Burst Test: on/off cycles.
    Tests cold start behavior, connection reuse, queue drain.
    Pattern: 60s at 50 users → 30s at 0 → repeat 10x
    """
    def tick(self):
        run_time = self.get_run_time()
        cycle_duration = 90  # 60s on + 30s off
        max_cycles = 10

        if run_time > cycle_duration * max_cycles:
            return None

        cycle_position = run_time % cycle_duration
        if cycle_position < 60:
            return (50, 10)
        else:
            return (0, 50)  # Ramp down quickly


class RampTestShape(LoadTestShape):
    """
    Ramp Test: linear increase to find breaking point.
    0 → 200 users over 10 minutes.
    """
    def tick(self):
        run_time = self.get_run_time()
        ramp_duration = 600  # 10 minutes
        max_users = 200

        if run_time > ramp_duration + 120:  # +2min hold at max
            return None

        if run_time <= ramp_duration:
            users = int(max_users * (run_time / ramp_duration))
        else:
            users = max_users

        spawn_rate = max(1, max_users // (ramp_duration // 3))
        return (max(1, users), spawn_rate)


class FlashCrowdShape(LoadTestShape):
    """
    Flash Crowd: exponential growth.
    Spawn rate doubles every 30 seconds.
    """
    def tick(self):
        run_time = self.get_run_time()
        if run_time > 300:  # 5 minutes max
            return None

        period = int(run_time / 30)
        spawn_rate = 2 ** period  # 1, 2, 4, 8, 16, 32, 64...
        users = min(spawn_rate * 30, 500)
        return (users, spawn_rate)


# ═══════════════════════════════════════
# User Personas
# ═══════════════════════════════════════

class BrowsingUser(HttpUser):
    """
    Casual browser — light, read-heavy traffic.
    Simulates typical web visitors browsing catalog.
    """
    weight = 5
    wait_time = between(1, 3)

    @task(10)
    def browse_products(self):
        page = random.randint(1, 50)
        self.client.get(
            f"/api/products?page={page}&per_page=20",
            name="/api/products [browse]",
        )

    @task(5)
    def view_product(self):
        product_id = random.randint(1, 1000)
        self.client.get(
            f"/api/products/{product_id}",
            name="/api/products/:id",
        )

    @task(3)
    def search_products(self):
        terms = ["smart", "wireless", "pro", "ultra", "mini", "max", "digital", "auto"]
        term = random.choice(terms)
        self.client.get(
            f"/api/products/search?q={term}",
            name="/api/products/search",
        )

    @task(2)
    def get_categories(self):
        self.client.get("/api/products/categories", name="/api/products/categories")

    @task(1)
    def check_health(self):
        self.client.get("/api/health", name="/api/health")

    @task(1)
    def check_metrics(self):
        self.client.get("/api/metrics", name="/api/metrics")


class ShoppingUser(HttpUser):
    """
    Active shopper — registers, browses, places orders.
    """
    weight = 3
    wait_time = between(2, 5)
    token = None
    user_id = None

    def on_start(self):
        email = random_email()
        username = random_username()
        password = "TestPass123!"

        with self.client.post(
            "/api/auth/register",
            json={"email": email, "username": username, "password": password},
            name="/api/auth/register",
            catch_response=True,
        ) as response:
            if response.status_code == 201:
                data = response.json()
                self.token = data["access_token"]
                self.user_id = data["user"]["id"]
                response.success()
            elif response.status_code == 409:
                with self.client.post(
                    "/api/auth/login",
                    json={"email": email, "password": password},
                    name="/api/auth/login",
                    catch_response=True,
                ) as login_resp:
                    if login_resp.status_code == 200:
                        data = login_resp.json()
                        self.token = data["access_token"]
                        self.user_id = data["user"]["id"]
                        login_resp.success()
                    else:
                        login_resp.failure(f"Login failed: {login_resp.status_code}")
                response.success()
            else:
                response.failure(f"Register failed: {response.status_code}")

    def _auth_headers(self):
        if self.token:
            return {"Authorization": f"Bearer {self.token}"}
        return {}

    @task(5)
    def browse_products(self):
        page = random.randint(1, 50)
        self.client.get(
            f"/api/products?page={page}&per_page=20",
            name="/api/products [shop]",
        )

    @task(3)
    def place_order(self):
        if not self.token:
            return
        num_items = random.randint(1, 5)
        items = [
            {"product_id": random.randint(1, 1000), "quantity": random.randint(1, 3)}
            for _ in range(num_items)
        ]
        self.client.post(
            "/api/orders",
            json={
                "items": items,
                "shipping_address": f"{random.randint(1, 9999)} Locust Ave, Test City, TS {random.randint(10000, 99999)}",
                "notes": "Locust order",
            },
            headers=self._auth_headers(),
            name="/api/orders [create]",
        )

    @task(2)
    def list_orders(self):
        if not self.token:
            return
        self.client.get(
            "/api/orders?page=1&per_page=20",
            headers=self._auth_headers(),
            name="/api/orders [list]",
        )

    @task(1)
    def order_stats(self):
        self.client.get("/api/orders/stats", name="/api/orders/stats")

    @task(1)
    def view_product(self):
        product_id = random.randint(1, 1000)
        self.client.get(f"/api/products/{product_id}", name="/api/products/:id [shop]")


class APIGatewayUser(HttpUser):
    """
    Simulates upstream API gateway traffic with realistic headers,
    auth tokens, retry logic. Models microservice-to-microservice calls.
    """
    weight = 3
    wait_time = between(0.5, 2)
    token = None

    def on_start(self):
        email = random_email()
        username = random_username()
        with self.client.post(
            "/api/auth/register",
            json={"email": email, "username": username, "password": "GatewayPass99!"},
            name="/api/auth/register [gateway]",
            catch_response=True,
        ) as resp:
            if resp.status_code in (201, 409):
                if resp.status_code == 201:
                    self.token = resp.json().get("access_token")
                else:
                    login = self.client.post(
                        "/api/auth/login",
                        json={"email": email, "password": "GatewayPass99!"},
                    )
                    if login.status_code == 200:
                        self.token = login.json().get("access_token")
                resp.success()

    def _headers(self):
        h = {
            "X-Request-ID": f"gw-{''.join(random.choices(string.hexdigits, k=16))}",
            "X-Forwarded-For": f"10.0.{random.randint(1,254)}.{random.randint(1,254)}",
            "User-Agent": "StressForge-Gateway/1.0",
        }
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    @task(5)
    def health_check(self):
        self.client.get("/api/health/ready", headers=self._headers(), name="/api/health/ready [gateway]")

    @task(4)
    def fetch_products(self):
        self.client.get(
            f"/api/products?page={random.randint(1,20)}&per_page=50",
            headers=self._headers(),
            name="/api/products [gateway]",
        )

    @task(3)
    def fetch_single_product(self):
        self.client.get(
            f"/api/products/{random.randint(1, 1000)}",
            headers=self._headers(),
            name="/api/products/:id [gateway]",
        )

    @task(2)
    def queue_depth(self):
        self.client.get("/api/queue/depth", headers=self._headers(), name="/api/queue/depth [gateway]")

    @task(1)
    def cluster_hpa(self):
        self.client.get("/api/cluster/hpa", headers=self._headers(), name="/api/cluster/hpa [gateway]")


class MobileClientUser(HttpUser):
    """
    Short sessions, slow network simulation, lots of GET requests with
    cache headers, occasional offline retry storms.
    """
    weight = 2
    wait_time = between(3, 8)  # Slower — mobile users are less active

    @task(6)
    def browse_catalog(self):
        # Mobile users request fewer items per page
        self.client.get(
            f"/api/products?page={random.randint(1,30)}&per_page=10",
            headers={
                "User-Agent": "StressForge-Mobile/1.0 (iOS 17.4)",
                "Cache-Control": "max-age=300",
            },
            name="/api/products [mobile]",
        )

    @task(4)
    def view_product_detail(self):
        pid = random.randint(1, 1000)
        self.client.get(
            f"/api/products/{pid}",
            headers={
                "If-None-Match": f"etag-{pid}-v1",
                "User-Agent": "StressForge-Mobile/1.0",
            },
            name="/api/products/:id [mobile]",
        )

    @task(2)
    def retry_storm(self):
        """Simulate offline retry storm — 3 rapid requests."""
        pid = random.randint(1, 500)
        for _ in range(3):
            self.client.get(
                f"/api/products/{pid}",
                headers={"User-Agent": "StressForge-Mobile/1.0 (retry)"},
                name="/api/products/:id [mobile-retry]",
            )

    @task(1)
    def search(self):
        terms = ["phone", "case", "charger", "cable", "screen"]
        self.client.get(
            f"/api/products/search?q={random.choice(terms)}",
            name="/api/products/search [mobile]",
        )


class BatchJobUser(HttpUser):
    """
    Hits /api/orders/bulk with 10-100 items. Models ETL pipelines.
    Drives queue depth and worker pressure.
    """
    weight = 2
    wait_time = between(5, 15)
    token = None

    def on_start(self):
        email = random_email()
        username = random_username()
        resp = self.client.post(
            "/api/auth/register",
            json={"email": email, "username": username, "password": "BatchPass123!"},
        )
        if resp.status_code in (200, 201):
            self.token = resp.json().get("access_token")
        elif resp.status_code == 409:
            resp2 = self.client.post(
                "/api/auth/login",
                json={"email": email, "password": "BatchPass123!"},
            )
            if resp2.status_code == 200:
                self.token = resp2.json().get("access_token")

    def _auth(self):
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    @task(5)
    def bulk_orders(self):
        if not self.token:
            return
        count = random.randint(10, 100)
        self.client.post(
            "/api/orders/bulk",
            json={"count": count},
            headers=self._auth(),
            name="/api/orders/bulk [batch]",
            timeout=120,
        )

    @task(3)
    def queue_burst(self):
        """Fire burst jobs to saturate queue."""
        count = random.randint(20, 100)
        intensity = random.randint(10, 50)
        self.client.post(
            "/api/queue/burst",
            json={"count": count, "intensity": intensity, "priority": random.choice(["high", "medium", "low"])},
            name="/api/queue/burst [batch]",
        )

    @task(2)
    def fire_chain(self):
        """Trigger a celery chain workflow."""
        self.client.post(
            "/api/jobs/chain",
            json={"intensity": random.randint(10, 40)},
            name="/api/jobs/chain [batch]",
        )

    @task(1)
    def fire_chord(self):
        """Trigger a fan-out chord workflow."""
        self.client.post(
            "/api/jobs/chord",
            json={"fan_out": random.randint(3, 10), "intensity": random.randint(10, 30)},
            name="/api/jobs/chord [batch]",
        )


class AdminUser(HttpUser):
    """
    Hits stats/aggregate endpoints, exports, reports.
    Lighter but causes heavy DB GROUP BY queries.
    """
    weight = 1
    wait_time = between(5, 15)

    @task(4)
    def order_stats(self):
        self.client.get("/api/orders/stats", name="/api/orders/stats [admin]")

    @task(3)
    def system_metrics(self):
        self.client.get("/api/metrics", name="/api/metrics [admin]")

    @task(3)
    def system_gauges(self):
        self.client.get("/api/metrics/system", name="/api/metrics/system [admin]")

    @task(2)
    def queue_depth(self):
        self.client.get("/api/queue/depth", name="/api/queue/depth [admin]")

    @task(2)
    def uptime_summary(self):
        self.client.get("/api/uptime/summary", name="/api/uptime/summary [admin]")

    @task(1)
    def uptime_incidents(self):
        self.client.get("/api/uptime/incidents", name="/api/uptime/incidents [admin]")

    @task(1)
    def cluster_hpa(self):
        self.client.get("/api/cluster/hpa", name="/api/cluster/hpa [admin]")

    @task(1)
    def circuit_breakers(self):
        self.client.get("/api/circuit-breakers", name="/api/circuit-breakers [admin]")

    @task(1)
    def test_runs(self):
        self.client.get("/api/runs?limit=20", name="/api/runs [admin]")


class StressUser(HttpUser):
    """
    Infrastructure stress testing — heavy workloads.
    Hits CPU/Memory/IO/Mixed/Distributed endpoints.
    """
    weight = 2
    wait_time = between(3, 8)

    @task(4)
    def stress_cpu(self):
        intensity = random.randint(10, 50)
        self.client.post(
            "/api/stress/cpu",
            json={"intensity": intensity, "duration_seconds": 5},
            name="/api/stress/cpu",
            timeout=120,
        )

    @task(3)
    def stress_memory(self):
        intensity = random.randint(5, 30)
        self.client.post(
            "/api/stress/memory",
            json={"intensity": intensity, "duration_seconds": 3},
            name="/api/stress/memory",
            timeout=60,
        )

    @task(3)
    def stress_io(self):
        intensity = random.randint(5, 30)
        self.client.post(
            "/api/stress/io",
            json={"intensity": intensity, "duration_seconds": 5},
            name="/api/stress/io",
            timeout=120,
        )

    @task(2)
    def stress_mixed(self):
        intensity = random.randint(10, 40)
        self.client.post(
            "/api/stress/mixed",
            json={"intensity": intensity, "duration_seconds": 5},
            name="/api/stress/mixed",
            timeout=120,
        )

    @task(2)
    def stress_celery(self):
        intensity = random.randint(10, 60)
        self.client.post(
            "/api/stress/celery",
            json={"intensity": intensity, "duration_seconds": 5},
            name="/api/stress/celery",
            timeout=60,
        )

    @task(1)
    def stress_distributed(self):
        intensity = random.randint(20, 60)
        self.client.post(
            "/api/stress/distributed",
            json={"intensity": intensity, "duration_seconds": 10},
            name="/api/stress/distributed",
            timeout=120,
        )

    @task(1)
    def readiness_check(self):
        self.client.get("/api/health/ready", name="/api/health/ready")


class AbusiveUser(HttpUser):
    """
    Hammers auth endpoints, sends malformed payloads, tests rate limiting.
    Low weight — every prod system gets these.
    """
    weight = 1
    wait_time = between(0.5, 2)

    @task(5)
    def brute_force_login(self):
        """Rapid login attempts — tests rate limiting."""
        self.client.post(
            "/api/auth/login",
            json={"email": f"hacker{random.randint(1,999)}@evil.com", "password": "wrong"},
            name="/api/auth/login [abuse]",
        )

    @task(3)
    def malformed_stress(self):
        """Send malformed payloads to stress endpoints."""
        with self.client.post(
            "/api/stress/cpu",
            json={"intensity": random.choice([-1, 0, 999, "abc"])},
            name="/api/stress/cpu [abuse]",
            catch_response=True,
        ) as resp:
            # We expect 422 — that means validation is working
            if resp.status_code == 422:
                resp.success()

    @task(3)
    def invalid_product(self):
        """Request non-existent products."""
        self.client.get(
            f"/api/products/{random.randint(99999, 999999)}",
            name="/api/products/:id [abuse]",
        )

    @task(2)
    def oversized_bulk(self):
        """Try to create too many orders at once."""
        with self.client.post(
            "/api/orders/bulk",
            json={"count": 9999},  # Should be capped at 1000
            name="/api/orders/bulk [abuse]",
            catch_response=True,
        ) as resp:
            if resp.status_code == 422:
                resp.success()

    @task(1)
    def flood_registrations(self):
        """Rapid registration attempts."""
        self.client.post(
            "/api/auth/register",
            json={"email": random_email(), "username": random_username(), "password": "Flood123!"},
            name="/api/auth/register [abuse]",
        )

    @task(1)
    def hit_circuit_breakers(self):
        """Check circuit breaker states."""
        self.client.get("/api/circuit-breakers", name="/api/circuit-breakers [abuse]")

    @task(2)
    def sql_injection_attempt(self):
        """Send SQL injection payloads — tests input sanitization."""
        payloads = [
            "'; DROP TABLE users;--",
            "1 OR 1=1",
            "admin'--",
            "1; WAITFOR DELAY '0:0:5'--",
            "<script>alert(1)</script>",
        ]
        with self.client.get(
            f"/api/products?search={random.choice(payloads)}",
            name="/api/products [sqli]",
            catch_response=True,
        ) as resp:
            # Any response is fine — we're testing that the app doesn't crash
            if resp.status_code in (200, 422, 400):
                resp.success()

    @task(2)
    def spoofed_ip_rate_limit(self):
        """Try to bypass rate limiting with X-Forwarded-For spoofing."""
        fake_ip = f"{random.randint(1,254)}.{random.randint(1,254)}.{random.randint(1,254)}.{random.randint(1,254)}"
        self.client.post(
            "/api/stress/cpu",
            json={"intensity": 10, "duration_seconds": 1},
            headers={"X-Forwarded-For": fake_ip, "X-Real-IP": fake_ip},
            name="/api/stress/cpu [spoofed-ip]",
        )

    @task(1)
    def check_cost_estimate(self):
        """Probe cost estimation endpoint."""
        self.client.get("/api/metrics/cost-estimate", name="/api/metrics/cost-estimate [abuse]")


# ═══════════════════════════════════════
# 9. DeepPaginationUser — v3.0
# ═══════════════════════════════════════

class DeepPaginationUser(HttpUser):
    """
    Always requests deep pages (page 500+) to expose OFFSET performance issues.
    Tests whether cursor-based pagination is implemented.
    """
    weight = 1
    wait_time = between(2, 5)

    @task(5)
    def deep_page_products(self):
        """Request pages 500+ — catastrophically slow with OFFSET at scale."""
        page = random.randint(500, 5000)
        self.client.get(
            f"/api/products?page={page}&limit=20",
            name="/api/products [deep-page]",
            timeout=30,
        )

    @task(3)
    def deep_page_orders(self):
        """Deep pages on orders."""
        page = random.randint(100, 1000)
        self.client.get(
            f"/api/orders?page={page}&limit=20",
            name="/api/orders [deep-page]",
            timeout=30,
        )

    @task(2)
    def check_latency_percentiles(self):
        """Monitor latency degradation during deep pagination."""
        self.client.get(
            "/api/metrics/latency-percentiles",
            name="/api/metrics/latency-percentiles",
        )

    @task(1)
    def check_db_pool(self):
        """Monitor pool status during heavy DB reads."""
        self.client.get("/api/metrics/db-pool", name="/api/metrics/db-pool")


# ═══════════════════════════════════════
# 10. ColdStartUser — v3.0
# ═══════════════════════════════════════

class ColdStartUser(HttpUser):
    """
    Triggers HPA scale-out then hammers new pods to measure cold-start latency.
    Tests readiness probe delay, cache warm-up, and connection pool initialization.
    """
    weight = 1
    wait_time = between(1, 3)

    @task(3)
    def trigger_scale_out(self):
        """Fire distributed stress to force HPA to add pods."""
        self.client.post(
            "/api/stress/distributed",
            json={"intensity": 60, "duration_seconds": 30},
            name="/api/stress/distributed [cold-start]",
            timeout=120,
        )

    @task(5)
    def hammer_after_scale(self):
        """Immediate rapid-fire requests after scaling, measuring cold-start penalty."""
        # Fast sequential hits — new pods will have cold caches
        for _ in range(5):
            self.client.get("/api/products?page=1&limit=50", name="/api/products [cold-hit]")
            self.client.get("/api/health/ready", name="/api/health/ready [cold-hit]")

    @task(3)
    def check_pod_age(self):
        """Monitor pod age and cache hit rate — shows warm-up progress."""
        self.client.get("/api/metrics/pod-age", name="/api/metrics/pod-age")

    @task(2)
    def check_pool_warmup(self):
        """Check if connection pool is warmed up on new pods."""
        self.client.get("/api/metrics/db-pool", name="/api/metrics/db-pool [cold-start]")

    @task(1)
    def check_hpa_status(self):
        """Watch HPA scaling events."""
        self.client.get("/api/cluster/hpa", name="/api/cluster/hpa [cold-start]")


# ═══════════════════════════════════════
# 11. TenantUser — v3.0
# ═══════════════════════════════════════

class TenantUser(HttpUser):
    """
    Multi-tenant load isolation testing.
    Each user is assigned a random tenant with a random SLA tier.
    Tests the noisy neighbor problem.
    """
    weight = 1
    wait_time = between(1, 4)

    def on_start(self):
        """Assign a random tenant ID and tier."""
        self.tenant_id = f"tenant-{random.randint(1, 10)}"
        self.tier = random.choice(["free", "pro", "enterprise"])

    @task(5)
    def tenant_stress(self):
        """Fire load scoped to this tenant's resource quota."""
        intensity = {"free": 10, "pro": 40, "enterprise": 80}[self.tier]
        self.client.post(
            f"/api/stress/tenants/{self.tenant_id}/stress",
            json={"intensity": intensity, "duration_seconds": 5},
            name=f"/api/stress/tenant [{ self.tier}]",
            timeout=60,
        )

    @task(3)
    def tenant_browse(self):
        """Browse as tenant — tests if high-tier tenants get better latency."""
        self.client.get(
            "/api/products?page=1&limit=20",
            name="/api/products [tenant]",
        )

    @task(2)
    def tenant_burst(self):
        """Queue burst as tenant — tests priority queue isolation."""
        priority = {"free": "low", "pro": "medium", "enterprise": "high"}[self.tier]
        self.client.post(
            "/api/queue/burst",
            json={"count": 10, "intensity": 20, "priority": priority},
            name=f"/api/queue/burst [tenant-{self.tier}]",
            timeout=30,
        )

    @task(1)
    def check_cost(self):
        """Monitor cost attribution per tenant."""
        self.client.get("/api/metrics/cost-estimate", name="/api/metrics/cost-estimate [tenant]")

