import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# Read the database address from the environment. If none is set, use a local
# SQLite file. This lets us switch to PostgreSQL later without changing code.
# The default database file is always wallet-api/trustflow.db, whichever folder a script is started from.
DEFAULT_DB = Path(__file__).resolve().parent / "trustflow.db"
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DEFAULT_DB.as_posix()}")

# SQLite needs this setting because the API may use it from several threads.
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False)


class Base(DeclarativeBase):
    """All table definitions inherit from this class."""


def get_db():
    """One database session per web request, always closed afterwards."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
