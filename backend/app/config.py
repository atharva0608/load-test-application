"""
StressForge Configuration — Environment-based settings.
"""
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # App
    APP_NAME: str = "StressForge"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    # Database
    DATABASE_URL: str = "postgresql://stressforge:stressforge_pass@postgres:5432/stressforge_db"

    # Redis
    REDIS_URL: str = "redis://redis:6379/0"

    # JWT
    JWT_SECRET_KEY: str = "stressforge-super-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_MINUTES: int = 60

    # Celery
    CELERY_BROKER_URL: str = "redis://redis:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://redis:6379/2"

    # Seed
    SEED_PRODUCTS: int = 1000
    SEED_ON_STARTUP: bool = True

    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    return Settings()
