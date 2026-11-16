from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base. Domain tables are registered by importing ``app.db.models``."""
