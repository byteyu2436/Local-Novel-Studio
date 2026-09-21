from app.adapters.sqlite import Base
from sqlalchemy import create_engine


def test_sqlalchemy_declarative_base_is_available() -> None:
    assert Base.__name__ == "Base"
    assert Base.metadata is not None


def test_declarative_base_binds_to_in_memory_sqlite() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    engine.dispose()
