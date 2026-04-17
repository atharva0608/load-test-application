"""
StressForge ORM Models — User, Product, Order, OrderItem, UptimeEvent, Incident, TestRun.
"""
from sqlalchemy import (
    Column, Integer, String, Float, Text, DateTime, ForeignKey, JSON, Boolean, Index
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    username = Column(String(100), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    orders = relationship("Order", back_populates="user")


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    description = Column(Text)
    price = Column(Float, nullable=False)
    stock = Column(Integer, default=0)
    category = Column(String(100), index=True)
    image_url = Column(String(500))
    sku = Column(String(50), unique=True, index=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Full-text search index
    __table_args__ = (
        Index("ix_products_name_desc", "name", "category"),
    )

    order_items = relationship("OrderItem", back_populates="product")


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    total = Column(Float, nullable=False, default=0.0)
    status = Column(String(50), default="pending", index=True)
    shipping_address = Column(Text)
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    user = relationship("User", back_populates="orders")
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    quantity = Column(Integer, nullable=False, default=1)
    unit_price = Column(Float, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    order = relationship("Order", back_populates="items")
    product = relationship("Product", back_populates="order_items")


# ── Uptime Monitoring Models ─────────────────────────

class UptimeEvent(Base):
    """Records individual health check heartbeats."""
    __tablename__ = "uptime_events"

    id = Column(Integer, primary_key=True, index=True)
    endpoint = Column(String(500), nullable=False, index=True)
    status = Column(String(50), nullable=False, index=True)  # healthy, degraded, down
    latency_ms = Column(Float, default=0.0)
    pod_name = Column(String(255))
    error_reason = Column(Text)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    __table_args__ = (
        Index("ix_uptime_events_endpoint_time", "endpoint", "timestamp"),
    )


class Incident(Base):
    """Records service incidents (3+ consecutive failures)."""
    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True, index=True)
    endpoint = Column(String(500), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False, index=True)
    resolved_at = Column(DateTime(timezone=True))
    duration_seconds = Column(Float)
    cause = Column(Text)
    affected_endpoints = Column(JSON)

    __table_args__ = (
        Index("ix_incidents_started", "started_at"),
    )


# ── Test Run Persistence ──────────────────────────────

class TestRun(Base):
    """Persists load test scenario runs for history and comparison."""
    __tablename__ = "test_runs"

    id = Column(Integer, primary_key=True, index=True)
    scenario_name = Column(String(255), nullable=False, index=True)
    status = Column(String(50), default="running", index=True)  # running, completed, failed, cancelled
    config_json = Column(JSON)
    summary_json = Column(JSON)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    ended_at = Column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_test_runs_scenario", "scenario_name", "started_at"),
    )


# ── Slow Request Tracking ─────────────────────────────

class SlowRequest(Base):
    """Records requests exceeding the latency threshold for inspection."""
    __tablename__ = "slow_requests"

    id = Column(Integer, primary_key=True, index=True)
    endpoint = Column(String(500), nullable=False, index=True)
    method = Column(String(10), nullable=False)
    duration_ms = Column(Float, nullable=False, index=True)
    db_query_count = Column(Integer, default=0)
    db_total_ms = Column(Float, default=0.0)
    redis_hit = Column(Boolean)
    payload_size = Column(Integer, default=0)
    status_code = Column(Integer)
    user_agent = Column(String(500))
    request_id = Column(String(50))
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    __table_args__ = (
        Index("ix_slow_requests_endpoint_time", "endpoint", "timestamp"),
    )

