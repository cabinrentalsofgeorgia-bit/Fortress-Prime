"""
FastAPI dependency providers for Fortress Prime.
"""

from backend.core.database import get_db

__all__ = ["get_db"]
