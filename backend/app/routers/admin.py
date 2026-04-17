"""
StressForge — Admin Router.
Bulk seeding, data volume scaling, administrative operations.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import text
import time
import random
import string
import logging

from app.database import get_db
from app.models import Product

router = APIRouter(prefix="/api/admin", tags=["admin"])
logger = logging.getLogger("stressforge.admin")


class SeedRequest(BaseModel):
    count: int = Field(default=10000, ge=100, le=10_000_000, description="Number of products to seed")
    batch_size: int = Field(default=1000, ge=100, le=10000, description="Batch insert size")
    clear_existing: bool = Field(default=False, description="Clear existing products before seeding")


class SeedResponse(BaseModel):
    status: str
    rows_created: int
    batches: int
    duration_seconds: float
    rows_per_second: float
    total_products: int


CATEGORIES = [
    "Electronics", "Clothing", "Books", "Home & Kitchen", "Sports",
    "Automotive", "Toys", "Health", "Garden", "Music",
    "Tools", "Pet Supplies", "Office", "Grocery", "Industrial",
    "Jewelry", "Beauty", "Baby", "Movies", "Software",
]

ADJECTIVES = [
    "Premium", "Ultra", "Pro", "Elite", "Advanced", "Smart", "Quantum",
    "Nano", "Mega", "Hyper", "Turbo", "Stealth", "Titan", "Nexus",
    "Apex", "Prime", "Fusion", "Zenith", "Nova", "Vertex",
]

NOUNS = [
    "Widget", "Gadget", "Device", "Module", "Sensor", "Controller",
    "Adapter", "Hub", "Switch", "Router", "Scanner", "Monitor",
    "Tracker", "Generator", "Processor", "Reader", "Charger",
    "Speaker", "Display", "Camera", "Printer", "Component",
]


def _generate_sku(idx: int) -> str:
    """Generate unique SKU like SF-A7K9-00001."""
    prefix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"SF-{prefix}-{idx:06d}"


@router.post("/seed", response_model=SeedResponse)
def bulk_seed(req: SeedRequest, db: Session = Depends(get_db)):
    """
    Seed N products in batches. Tests DB write throughput at scale.
    Use counts of 100K/1M/10M to test index performance degradation.
    """
    start = time.time()
    logger.info(f"🌱 Starting bulk seed: {req.count:,} products in batches of {req.batch_size}")

    if req.clear_existing:
        db.execute(text("DELETE FROM order_items WHERE product_id IN (SELECT id FROM products WHERE sku LIKE 'SF-%')"))
        db.execute(text("DELETE FROM products WHERE sku LIKE 'SF-%'"))
        db.commit()
        logger.info("🗑️ Cleared existing seeded products")

    # Get current max ID for offset
    result = db.execute(text("SELECT COALESCE(MAX(id), 0) FROM products"))
    offset = result.scalar() or 0

    created = 0
    batches = 0

    for batch_start in range(0, req.count, req.batch_size):
        batch_end = min(batch_start + req.batch_size, req.count)
        products = []

        for i in range(batch_start, batch_end):
            idx = offset + i + 1
            adj = random.choice(ADJECTIVES)
            noun = random.choice(NOUNS)
            cat = random.choice(CATEGORIES)
            products.append(Product(
                name=f"{adj} {noun} {idx}",
                description=f"Production-grade {adj.lower()} {noun.lower()} for infrastructure testing. SKU batch #{batches + 1}.",
                price=round(random.uniform(1.99, 999.99), 2),
                stock=random.randint(0, 10000),
                category=cat,
                sku=_generate_sku(idx),
                is_active=True,
            ))

        db.bulk_save_objects(products)
        db.commit()
        created += len(products)
        batches += 1

        if batches % 10 == 0:
            logger.info(f"  📦 Progress: {created:,} / {req.count:,} ({created / req.count * 100:.1f}%)")

    duration = time.time() - start

    # Get total count
    total = db.execute(text("SELECT COUNT(*) FROM products")).scalar()

    logger.info(f"✅ Bulk seed complete: {created:,} rows in {duration:.2f}s ({created / duration:.0f} rows/sec)")

    return SeedResponse(
        status="completed",
        rows_created=created,
        batches=batches,
        duration_seconds=round(duration, 3),
        rows_per_second=round(created / max(duration, 0.001), 1),
        total_products=total,
    )
