from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

engine = None
SessionLocal = None

Base = declarative_base()


def init_db(database_url: str):
    global engine, SessionLocal
    engine = create_engine(database_url, echo=False, future=True)
    SessionLocal = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, class_=Session
    )
    return engine


@contextmanager
def db_session() -> Session:
    if SessionLocal is None:
        raise RuntimeError("DB is not initialized. Call init_db() first.")
    session: Session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

