"""
StressForge CRUD Operations — Database access layer.
"""
from sqlalchemy.orm import Session
from sqlalchemy import or_, func
from app.models import User, Product, Order, OrderItem
from app.schemas import ProductCreate, OrderCreate, OrderItemCreate
from typing import Optional, List
import math


# ── User CRUD ─────────────────────────────────────────
def get_user_by_email(db: Session, email: str) -> Optional[User]:
    return db.query(User).filter(User.email == email).first()


def get_user_by_username(db: Session, username: str) -> Optional[User]:
    return db.query(User).filter(User.username == username).first()


def create_user(db: Session, email: str, username: str, hashed_password: str) -> User:
    user = User(email=email, username=username, hashed_password=hashed_password)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_user_count(db: Session) -> int:
    return db.query(func.count(User.id)).scalar()


# ── Product CRUD ──────────────────────────────────────
def get_products(
    db: Session,
    page: int = 1,
    per_page: int = 20,
    category: Optional[str] = None,
    search: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
):
    query = db.query(Product).filter(Product.is_active == True)  # noqa: E712

    if category:
        query = query.filter(Product.category == category)

    if search:
        query = query.filter(
            or_(
                Product.name.ilike(f"%{search}%"),
                Product.description.ilike(f"%{search}%"),
            )
        )

    if min_price is not None:
        query = query.filter(Product.price >= min_price)

    if max_price is not None:
        query = query.filter(Product.price <= max_price)

    total = query.count()
    pages = math.ceil(total / per_page) if per_page > 0 else 0
    items = query.offset((page - 1) * per_page).limit(per_page).all()

    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": pages,
    }


def get_product_by_id(db: Session, product_id: int) -> Optional[Product]:
    return db.query(Product).filter(Product.id == product_id).first()


def get_product_by_sku(db: Session, sku: str) -> Optional[Product]:
    return db.query(Product).filter(Product.sku == sku).first()


def create_product(db: Session, product_data: ProductCreate) -> Product:
    product = Product(**product_data.model_dump())
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


def get_product_count(db: Session) -> int:
    return db.query(func.count(Product.id)).scalar()


def get_categories(db: Session) -> List[str]:
    rows = db.query(Product.category).distinct().all()
    return [r[0] for r in rows if r[0]]


# ── Order CRUD ────────────────────────────────────────
def create_order(db: Session, user_id: int, order_data: OrderCreate) -> Order:
    order = Order(
        user_id=user_id,
        shipping_address=order_data.shipping_address,
        notes=order_data.notes,
        status="pending",
        total=0.0,
    )
    db.add(order)
    db.flush()  # Get order.id

    total = 0.0
    for item_data in order_data.items:
        product = db.query(Product).filter(Product.id == item_data.product_id).first()
        if product and product.stock >= item_data.quantity:
            unit_price = product.price
            order_item = OrderItem(
                order_id=order.id,
                product_id=item_data.product_id,
                quantity=item_data.quantity,
                unit_price=unit_price,
            )
            db.add(order_item)
            product.stock -= item_data.quantity
            total += unit_price * item_data.quantity

    order.total = total
    db.commit()
    db.refresh(order)
    return order


def get_order_by_id(db: Session, order_id: int) -> Optional[Order]:
    return db.query(Order).filter(Order.id == order_id).first()


def get_user_orders(db: Session, user_id: int, page: int = 1, per_page: int = 20):
    query = db.query(Order).filter(Order.user_id == user_id).order_by(Order.created_at.desc())
    total = query.count()
    items = query.offset((page - 1) * per_page).limit(per_page).all()
    return {"items": items, "total": total, "page": page, "per_page": per_page}


def get_order_count(db: Session) -> int:
    return db.query(func.count(Order.id)).scalar()


def get_order_stats(db: Session) -> dict:
    total_orders = db.query(func.count(Order.id)).scalar()
    total_revenue = db.query(func.sum(Order.total)).scalar() or 0.0
    pending = db.query(func.count(Order.id)).filter(Order.status == "pending").scalar()
    completed = db.query(func.count(Order.id)).filter(Order.status == "completed").scalar()
    return {
        "total_orders": total_orders,
        "total_revenue": round(total_revenue, 2),
        "pending": pending,
        "completed": completed,
    }
