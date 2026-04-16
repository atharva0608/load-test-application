"""
StressForge Product Router — CRUD + Search with Redis caching.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas import ProductResponse, ProductListResponse, ProductCreate
from app.crud import get_products, get_product_by_id, create_product, get_product_by_sku, get_categories
from app.auth import get_current_user
from app.models import User
import json
import redis
from app.config import get_settings

settings = get_settings()
router = APIRouter(prefix="/api/products", tags=["Products"])

# Redis client (lazy init)
_redis = None


def get_redis():
    global _redis
    if _redis is None:
        try:
            _redis = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
            _redis.ping()
        except Exception:
            _redis = None
    return _redis


@router.get("", response_model=ProductListResponse)
def list_products(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    category: str = Query(None),
    search: str = Query(None),
    min_price: float = Query(None, ge=0),
    max_price: float = Query(None, ge=0),
    db: Session = Depends(get_db),
):
    """List products with pagination, filtering, and search — I/O intensive."""
    result = get_products(db, page, per_page, category, search, min_price, max_price)
    return ProductListResponse(
        items=[ProductResponse.model_validate(p) for p in result["items"]],
        total=result["total"],
        page=result["page"],
        per_page=result["per_page"],
        pages=result["pages"],
    )


@router.get("/categories")
def list_categories(db: Session = Depends(get_db)):
    """Get all product categories."""
    return {"categories": get_categories(db)}


@router.get("/search")
def search_products(
    q: str = Query(..., min_length=1),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Full-text search across products — CPU + I/O intensive."""
    result = get_products(db, page, per_page, search=q)
    return ProductListResponse(
        items=[ProductResponse.model_validate(p) for p in result["items"]],
        total=result["total"],
        page=result["page"],
        per_page=result["per_page"],
        pages=result["pages"],
    )


@router.get("/{product_id}", response_model=ProductResponse)
def get_product(product_id: int, db: Session = Depends(get_db)):
    """Get a single product — uses Redis cache with DB fallback."""
    r = get_redis()
    cache_key = f"product:{product_id}"

    # Try cache first
    if r:
        try:
            cached = r.get(cache_key)
            if cached:
                return ProductResponse(**json.loads(cached))
        except Exception:
            pass

    # DB fallback
    product = get_product_by_id(db, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    response = ProductResponse.model_validate(product)

    # Cache for 5 minutes
    if r:
        try:
            r.setex(cache_key, 300, response.model_dump_json())
        except Exception:
            pass

    return response


@router.post("", response_model=ProductResponse, status_code=201)
def add_product(
    data: ProductCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new product (authenticated)."""
    if get_product_by_sku(db, data.sku):
        raise HTTPException(status_code=409, detail="SKU already exists")

    product = create_product(db, data)

    # Invalidate cache
    r = get_redis()
    if r:
        try:
            r.delete(f"product:{product.id}")
        except Exception:
            pass

    return ProductResponse.model_validate(product)
