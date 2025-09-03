import os
from pathlib import Path
from sqlalchemy import (
    create_engine,
    Column,
    String,
    Text,
    JSON,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base


def _get_database_url() -> str:
    """Resolve database URL used for the TCG cards storage.

    The previous implementation relied on the current working directory,
    which meant executing the seed script from a different folder would
    create a brand new database elsewhere.  To keep things consistent with
    the main project, we look for the same environment variables accepted by
    ``config.py`` and fall back to a path relative to this file.
    """

    url = (
        os.environ.get("DATABASE_URL")
        or os.environ.get("DB_URL")
        or os.environ.get("SQLALCHEMY_DATABASE_URI")
    )
    if url:
        return url

    root = Path(__file__).resolve().parent
    db_path = root / "database" / "poketcg.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{db_path.as_posix()}"


DATABASE_URL = _get_database_url()
engine = create_engine(DATABASE_URL, future=True)
Base = declarative_base()


class Card(Base):
    __tablename__ = "cards"
    id = Column(String, primary_key=True)
    series_name = Column(String, nullable=False, index=True)
    set_name = Column(String, nullable=False, index=True)
    file_local_id = Column(String, nullable=False, index=True)
    name_en = Column(String)
    name_pt = Column(String)
    rarity = Column(String)
    category = Column(String)
    types_json = Column(Text)
    data_json = Column(JSON)

    __table_args__ = (
        UniqueConstraint("series_name", "set_name", "file_local_id", name="uq_series_set_file"),
    )


def get_engine():
    return engine
