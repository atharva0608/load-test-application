"""
StressForge — Locust Load Testing Scenarios.

Three user personas with different traffic patterns:
1. BrowsingUser (weight=5) — Light load: reads products, browses catalog
2. ShoppingUser (weight=3) — Medium load: registers, shops, places orders
3. StressUser  (weight=2) — Heavy load: hits CPU/Memory/IO stress endpoints
"""
from locust import HttpUser, task, between, events
import random
import string
import json
import logging

logger = logging.getLogger(__name__)


def random_email():
    """Generate a unique random email."""
    rand = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
    return f"user_{rand}@stressforge.test"


def random_username():
    """Generate a unique random username."""
    rand = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    return f"sf_{rand}"


class BrowsingUser(HttpUser):
    """
    Simulates a casual browser — light, read-heavy traffic.
    Weight: 5 (most common user type)
    """
    weight = 5
    wait_time = between(1, 3)

    @task(10)
    def browse_products(self):
        """Browse product catalog with pagination."""
        page = random.randint(1, 50)
        self.client.get(
            f"/api/products?page={page}&per_page=20",
            name="/api/products [browse]",
        )

    @task(5)
    def view_product(self):
        """View a single product (uses Redis cache)."""
        product_id = random.randint(1, 1000)
        self.client.get(
            f"/api/products/{product_id}",
            name="/api/products/:id",
        )

    @task(3)
    def search_products(self):
        """Search products by keyword."""
        terms = ["smart", "wireless", "pro", "ultra", "mini", "max", "digital", "auto"]
        term = random.choice(terms)
        self.client.get(
            f"/api/products/search?q={term}",
            name="/api/products/search",
        )

    @task(2)
    def get_categories(self):
        """Load product categories."""
        self.client.get("/api/products/categories", name="/api/products/categories")

    @task(1)
    def check_health(self):
        """Hit the health endpoint."""
        self.client.get("/api/health", name="/api/health")

    @task(1)
    def check_metrics(self):
        """Hit the metrics endpoint."""
        self.client.get("/api/metrics", name="/api/metrics")


class ShoppingUser(HttpUser):
    """
    Simulates an active shopper — registers, browses, places orders.
    Weight: 3
    """
    weight = 3
    wait_time = between(2, 5)
    token = None
    user_id = None

    def on_start(self):
        """Register a new user on start."""
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
                # User exists, try login
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
        """Browse products."""
        page = random.randint(1, 50)
        self.client.get(
            f"/api/products?page={page}&per_page=20",
            name="/api/products [shop]",
        )

    @task(3)
    def place_order(self):
        """Place a single order with random products."""
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
        """List user's orders."""
        if not self.token:
            return
        self.client.get(
            "/api/orders?page=1&per_page=20",
            headers=self._auth_headers(),
            name="/api/orders [list]",
        )

    @task(1)
    def order_stats(self):
        """Get order statistics."""
        self.client.get("/api/orders/stats", name="/api/orders/stats")

    @task(1)
    def view_product(self):
        """View single product."""
        product_id = random.randint(1, 1000)
        self.client.get(f"/api/products/{product_id}", name="/api/products/:id [shop]")


class StressUser(HttpUser):
    """
    Simulates infrastructure stress testing — heavy workloads.
    Weight: 2
    """
    weight = 2
    wait_time = between(3, 8)

    @task(4)
    def stress_cpu(self):
        """CPU-intensive workload."""
        intensity = random.randint(10, 50)
        self.client.post(
            "/api/stress/cpu",
            json={"intensity": intensity, "duration_seconds": 5},
            name="/api/stress/cpu",
            timeout=120,
        )

    @task(3)
    def stress_memory(self):
        """Memory-intensive workload."""
        intensity = random.randint(5, 30)
        self.client.post(
            "/api/stress/memory",
            json={"intensity": intensity, "duration_seconds": 3},
            name="/api/stress/memory",
            timeout=60,
        )

    @task(3)
    def stress_io(self):
        """I/O-intensive workload."""
        intensity = random.randint(5, 30)
        self.client.post(
            "/api/stress/io",
            json={"intensity": intensity, "duration_seconds": 5},
            name="/api/stress/io",
            timeout=120,
        )

    @task(2)
    def stress_mixed(self):
        """Mixed workload — full stack stress."""
        intensity = random.randint(10, 40)
        self.client.post(
            "/api/stress/mixed",
            json={"intensity": intensity, "duration_seconds": 5},
            name="/api/stress/mixed",
            timeout=120,
        )

    @task(1)
    def readiness_check(self):
        """Check readiness (DB + Redis connectivity)."""
        self.client.get("/api/health/ready", name="/api/health/ready")
