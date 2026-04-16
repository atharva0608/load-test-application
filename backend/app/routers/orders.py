"""
StressForge Orders Router — Order placement + bulk operations.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas import OrderCreate, OrderResponse, BulkOrderCreate
from app.crud import create_order, get_order_by_id, get_user_orders, get_order_stats, get_product_count
from app.auth import get_current_user
from app.models import User
import random
import time

router = APIRouter(prefix="/api/orders", tags=["Orders"])


@router.post("", response_model=OrderResponse, status_code=201)
def place_order(
    data: OrderCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Place a new order — multi-table transaction, I/O + CPU intensive."""
    order = create_order(db, current_user.id, data)
    if not order.items:
        raise HTTPException(status_code=400, detail="No valid items in order (check stock/product IDs)")
    return OrderResponse.model_validate(order)


@router.get("", response_model=dict)
def list_orders(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List current user's orders."""
    result = get_user_orders(db, current_user.id, page, per_page)
    return {
        "items": [OrderResponse.model_validate(o) for o in result["items"]],
        "total": result["total"],
        "page": result["page"],
        "per_page": result["per_page"],
    }


@router.get("/stats")
def order_stats(db: Session = Depends(get_db)):
    """Get order statistics — aggregate queries."""
    return get_order_stats(db)


@router.get("/{order_id}", response_model=OrderResponse)
def get_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a specific order by ID."""
    order = get_order_by_id(db, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    return OrderResponse.model_validate(order)


@router.post("/bulk", response_model=dict, status_code=201)
def bulk_create_orders(
    data: BulkOrderCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create multiple random orders — HEAVY I/O stress test.
    Each order contains 1-5 random products.
    """
    start = time.time()
    product_count = get_product_count(db)
    if product_count == 0:
        raise HTTPException(status_code=400, detail="No products available")

    created = 0
    errors = 0
    max_product_id = min(product_count, 1000)

    for _ in range(data.count):
        try:
            num_items = random.randint(1, 5)
            product_ids = random.sample(range(1, max_product_id + 1), min(num_items, max_product_id))
            order_data = OrderCreate(
                items=[
                    {"product_id": pid, "quantity": random.randint(1, 3)}
                    for pid in product_ids
                ],
                shipping_address=f"{random.randint(1, 9999)} Test Street, City, ST {random.randint(10000, 99999)}",
                notes=f"Bulk order #{_ + 1}",
            )
            create_order(db, current_user.id, order_data)
            created += 1
        except Exception:
            errors += 1

    duration = time.time() - start
    return {
        "created": created,
        "errors": errors,
        "total_requested": data.count,
        "duration_seconds": round(duration, 3),
        "orders_per_second": round(created / duration, 2) if duration > 0 else 0,
    }
