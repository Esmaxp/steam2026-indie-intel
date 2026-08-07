from sqlalchemy import Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models._types import TimestampMixin, pg_enum
from app.models.associations import game_developers, game_publishers
from app.models.enums import DataStatus


class Developer(Base, TimestampMixin):
    __tablename__ = "developers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True, index=True)
    country: Mapped[str | None] = mapped_column(Text)
    country_status: Mapped[DataStatus] = mapped_column(
        pg_enum(DataStatus, "data_status"), default=DataStatus.UNKNOWN
    )
    website: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)

    games: Mapped[list["Game"]] = relationship(  # noqa: F821
        secondary=game_developers, back_populates="developers"
    )


class Publisher(Base, TimestampMixin):
    __tablename__ = "publishers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True, index=True)
    country: Mapped[str | None] = mapped_column(Text)
    country_status: Mapped[DataStatus] = mapped_column(
        pg_enum(DataStatus, "data_status"), default=DataStatus.UNKNOWN
    )
    website: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)

    games: Mapped[list["Game"]] = relationship(  # noqa: F821
        secondary=game_publishers, back_populates="publishers"
    )
