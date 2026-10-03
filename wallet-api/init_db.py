from database import Base, engine
import models  # noqa: F401  (importing registers the tables)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


if __name__ == "__main__":
    init_db()
    print("Tables created:", ", ".join(Base.metadata.tables.keys()))
