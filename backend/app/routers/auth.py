"""
StressForge Auth Router — Registration and Login.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas import UserRegister, UserLogin, TokenResponse, UserResponse
from app.auth import hash_password, verify_password, create_access_token
from app.crud import get_user_by_email, get_user_by_username, create_user

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


@router.post("/register", response_model=TokenResponse, status_code=201)
def register(data: UserRegister, db: Session = Depends(get_db)):
    """Register a new user — CPU-intensive bcrypt hashing."""
    # Check duplicates
    if get_user_by_email(db, data.email):
        raise HTTPException(status_code=409, detail="Email already registered")
    if get_user_by_username(db, data.username):
        raise HTTPException(status_code=409, detail="Username already taken")

    # Hash password (CPU-intensive)
    hashed = hash_password(data.password)
    user = create_user(db, data.email, data.username, hashed)

    # Generate JWT
    token = create_access_token({"sub": str(user.id), "email": user.email})

    return TokenResponse(
        access_token=token,
        user=UserResponse.model_validate(user),
    )


@router.post("/login", response_model=TokenResponse)
def login(data: UserLogin, db: Session = Depends(get_db)):
    """Login — bcrypt verify is CPU-intensive."""
    user = get_user_by_email(db, data.email)
    if not user or not verify_password(data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token({"sub": str(user.id), "email": user.email})

    return TokenResponse(
        access_token=token,
        user=UserResponse.model_validate(user),
    )
