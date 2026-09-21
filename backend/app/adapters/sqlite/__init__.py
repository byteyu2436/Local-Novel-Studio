"""SQLite adapter package.

Engine, session factory, DATA_DIR initialization, and Alembic belong to a
later Issue. This module only reserves the SQLAlchemy 2 declarative base.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for future domain models."""
