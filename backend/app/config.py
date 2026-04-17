"""
StressForge Configuration — Environment-based settings.
"""
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # App
    APP_NAME: str = "StressForge"
    APP_VERSION: str = "3.0.0"
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

    # Performance thresholds
    SLOW_REQUEST_THRESHOLD_MS: float = 1000.0

    # AWS cost simulation rates
    COST_CPU_PER_HOUR: float = 0.0416  # t3.medium equivalent
    COST_IOPS_PER_1000: float = 0.005
    COST_DATA_TRANSFER_PER_GB: float = 0.09
    COST_CELERY_PER_1000: float = 0.02

    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    return Settings()
