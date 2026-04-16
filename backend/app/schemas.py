"""
StressForge Pydantic Schemas — Request/Response models.
"""
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime


# ── Auth ──────────────────────────────────────────────
class UserRegister(BaseModel):
    email: str = Field(..., min_length=5, max_length=255)
    username: str = Field(..., min_length=3, max_length=100)
    password: str = Field(..., min_length=6, max_length=100)


class UserLogin(BaseModel):
    email: str
    password: str


class UserResponse(BaseModel):
    id: int
    email: str
    username: str
    is_active: bool
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


# ── Products ──────────────────────────────────────────
class ProductCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    price: float = Field(..., gt=0)
    stock: int = Field(0, ge=0)
    category: Optional[str] = None
    image_url: Optional[str] = None
    sku: str = Field(..., min_length=1, max_length=50)


class ProductResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    price: float
    stock: int
    category: Optional[str]
    image_url: Optional[str]
    sku: str
    is_active: bool
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ProductListResponse(BaseModel):
    items: List[ProductResponse]
    total: int
    page: int
    per_page: int
    pages: int


# ── Orders ────────────────────────────────────────────
class OrderItemCreate(BaseModel):
    product_id: int
    quantity: int = Field(1, ge=1)


class OrderCreate(BaseModel):
    items: List[OrderItemCreate] = Field(..., min_length=1)
    shipping_address: Optional[str] = None
    notes: Optional[str] = None


class OrderItemResponse(BaseModel):
    id: int
    product_id: int
    quantity: int
    unit_price: float

    class Config:
        from_attributes = True


class OrderResponse(BaseModel):
    id: int
    user_id: int
    total: float
    status: str
    shipping_address: Optional[str]
    notes: Optional[str]
    items: List[OrderItemResponse]
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class BulkOrderCreate(BaseModel):
    count: int = Field(10, ge=1, le=1000)


# ── Stress ────────────────────────────────────────────
class StressRequest(BaseModel):
    intensity: int = Field(10, ge=1, le=100, description="Workload intensity 1-100")
    duration_seconds: Optional[int] = Field(5, ge=1, le=60, description="Duration in seconds")


class StressResponse(BaseModel):
    type: str
    intensity: int
    duration_ms: float
    result: Optional[str] = None
    details: Optional[dict] = None


# ── Health ────────────────────────────────────────────
class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    uptime_seconds: float


class ReadinessResponse(BaseModel):
    status: str
    database: str
    redis: str
    details: Optional[dict] = None
