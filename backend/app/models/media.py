from sqlalchemy import BigInteger, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models._types import pg_enum
from app.models.enums import MediaType


class MediaAsset(Base):
    __tablename__ = "media_assets"

    id: Mapped[int] = mapped_column(primary_key=True)
    appid: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("games.appid", ondelete="CASCADE"), index=True
    )
    media_type: Mapped[MediaType] = mapped_column(pg_enum(MediaType, "media_type"))
    url: Mapped[str] = mapped_column(Text)
    thumbnail_url: Mapped[str | None] = mapped_column(Text)
    position: Mapped[int | None] = mapped_column(Integer)
    local_path: Mapped[str | None] = mapped_column(Text)

    game: Mapped["Game"] = relationship(back_populates="media_assets")  # noqa: F821
