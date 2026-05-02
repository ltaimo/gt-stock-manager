from contextlib import contextmanager
from collections.abc import Iterator

from sqlalchemy.orm import Session


@contextmanager
def atomic(db: Session) -> Iterator[None]:
    try:
        yield
        db.commit()
    except Exception:
        db.rollback()
        raise
