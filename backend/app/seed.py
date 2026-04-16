"""
StressForge Seed — Populate database with realistic test data.
"""
from faker import Faker
from sqlalchemy.orm import Session
from app.models import Product
from app.crud import get_product_count
import random
import logging

logger = logging.getLogger(__name__)
fake = Faker()

CATEGORIES = [
    "Electronics", "Clothing", "Home & Garden", "Sports",
    "Books", "Toys", "Automotive", "Health", "Food", "Office"
]


def seed_products(db: Session, count: int = 1000):
    """Seed the database with fake products."""
    existing = get_product_count(db)
    if existing >= count:
        logger.info(f"Database already has {existing} products, skipping seed.")
        return

    to_create = count - existing
    logger.info(f"Seeding {to_create} products...")

    products = []
    for i in range(to_create):
        product = Product(
            name=fake.catch_phrase(),
            description=fake.paragraph(nb_sentences=3),
            price=round(random.uniform(1.99, 999.99), 2),
            stock=random.randint(0, 500),
            category=random.choice(CATEGORIES),
            image_url=f"https://picsum.photos/seed/{existing + i}/400/400",
            sku=f"SF-{existing + i + 1:06d}",
            is_active=True,
        )
        products.append(product)

        # Batch insert every 100 products
        if len(products) >= 100:
            db.bulk_save_objects(products)
            db.commit()
            products = []

    # Insert remaining
    if products:
        db.bulk_save_objects(products)
        db.commit()

    logger.info(f"Seeded {to_create} products successfully.")
