import datetime

from sqlalchemy import Boolean, Date, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.associations import game_festivals


class Festival(Base):
    """Steam festivals/events, e.g. Steam Next Fest editions."""

    __tablename__ = "festivals"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    is_next_fest: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    start_date: Mapped[datetime.date | None] = mapped_column(Date)
    end_date: Mapped[datetime.date | None] = mapped_column(Date)

    games: Mapped[list["Game"]] = relationship(  # noqa: F821
        secondary=game_festivals, back_populates="festivals"
    )
