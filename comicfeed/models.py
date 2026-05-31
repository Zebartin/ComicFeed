from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class GlobalSetting(Base):
    __tablename__ = "global_setting"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(String(1024))


class Subscription(Base):
    __tablename__ = "subscription"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(256))
    source_key: Mapped[str] = mapped_column(String(64))
    query: Mapped[str] = mapped_column(Text)
    mode: Mapped[str] = mapped_column(String(32), default="SEARCH")
    interval_minutes: Mapped[int] = mapped_column(Integer, default=360)
    cbz_max_pages: Mapped[int] = mapped_column(Integer, default=30)  # 0 = 不分卷
    sort: Mapped[str] = mapped_column(String(32), default="date")
    download_dir: Mapped[str] = mapped_column(Text, default="")
    filter_rules: Mapped[str] = mapped_column(Text, default="")  # JSON: [{"field":"num_favorites","op":"gte","value":100}]
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Gallery(Base):
    __tablename__ = "gallery"

    id: Mapped[str] = mapped_column(String(256), primary_key=True)
    source_key: Mapped[str] = mapped_column(String(64))
    native_id: Mapped[str] = mapped_column(String(128))
    normalized_title: Mapped[str] = mapped_column(Text)
    cover_url: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[str] = mapped_column(Text, default="")  # JSON 字符串
    num_favorites: Mapped[int] = mapped_column(Integer, default=0)
    reported_pages: Mapped[int] = mapped_column(Integer, default=0)
    actual_pages: Mapped[int] = mapped_column(Integer, default=0)
    web_url: Mapped[str] = mapped_column(Text, default="")
    downloaded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Page(Base):
    __tablename__ = "page"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    gallery_id: Mapped[str] = mapped_column(ForeignKey("gallery.id"))
    page_native_id: Mapped[str] = mapped_column(String(256))


class SourceCredential(Base):
    __tablename__ = "source_credential"

    source_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    encrypted_value: Mapped[str] = mapped_column(Text)


class SystemLog(Base):
    __tablename__ = "system_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    level: Mapped[str] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text)
