"""Many-to-many junction tables. Steam AppID is the game-side key everywhere."""

from sqlalchemy import BigInteger, Column, ForeignKey, Integer, Table, Text

from app.db.base import Base

game_developers = Table(
    "game_developers",
    Base.metadata,
    Column("appid", BigInteger, ForeignKey("games.appid", ondelete="CASCADE"), primary_key=True),
    Column(
        "developer_id",
        Integer,
        ForeignKey("developers.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)

game_publishers = Table(
    "game_publishers",
    Base.metadata,
    Column("appid", BigInteger, ForeignKey("games.appid", ondelete="CASCADE"), primary_key=True),
    Column(
        "publisher_id",
        Integer,
        ForeignKey("publishers.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)

game_genres = Table(
    "game_genres",
    Base.metadata,
    Column("appid", BigInteger, ForeignKey("games.appid", ondelete="CASCADE"), primary_key=True),
    Column("genre_id", Integer, ForeignKey("genres.id", ondelete="CASCADE"), primary_key=True),
    # Steam's original appdetails order — mirrors game_tags.rank.
    Column("rank", Integer, nullable=False, server_default="1"),
)

game_tags = Table(
    "game_tags",
    Base.metadata,
    Column("appid", BigInteger, ForeignKey("games.appid", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
    Column("rank", Integer, nullable=True),
    Column("votes", Integer, nullable=True),
)

game_festivals = Table(
    "game_festivals",
    Base.metadata,
    Column("appid", BigInteger, ForeignKey("games.appid", ondelete="CASCADE"), primary_key=True),
    Column(
        "festival_id",
        Integer,
        ForeignKey("festivals.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("source_url", Text, nullable=True),
    Column("notes", Text, nullable=True),
)
