import os
from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


@lru_cache
def engine() -> Engine:
    database_url = os.environ.get("DATABASE_URL")
    if database_url is None:
        raise RuntimeError("DATABASE_URL must be configured before database access")
    return create_engine(database_url.replace("postgresql://", "postgresql+psycopg://", 1))


def get_session() -> Generator[Session]:
    database_session = sessionmaker(bind=engine())()
    try:
        yield database_session
    finally:
        database_session.close()
