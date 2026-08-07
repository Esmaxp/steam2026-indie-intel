from sqlalchemy import Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.associations import game_genres, game_tags


class Genre(Base):
    __tablename__ = "genres"

    id: Mapped[int] = mapped_column(primary_key=True)
    steam_genre_id: Mapped[str | None] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text, unique=True, index=True)

    games: Mapped[list["Game"]] = relationship(  # noqa: F821
        secondary=game_genres, back_populates="genres"
    )


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True, index=True)

    games: Mapped[list["Game"]] = relationship(  # noqa: F821
        secondary=game_tags, back_populates="tags"
    )
