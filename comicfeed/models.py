from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Source(Base):
    __tablename__ = "source"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


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
    cross_source_dedup: Mapped[bool] = mapped_column(Boolean, default=True)
    sort: Mapped[str] = mapped_column(String(32), default="date")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    galleries: Mapped[list["SubscriptionGallery"]] = relationship(back_populates="subscription", lazy="selectin")


class Gallery(Base):
    __tablename__ = "gallery"

    id: Mapped[str] = mapped_column(String(256), primary_key=True)
    source_key: Mapped[str] = mapped_column(String(64))
    native_id: Mapped[str] = mapped_column(String(128))
    normalized_title: Mapped[str] = mapped_column(Text)
    display_title: Mapped[str] = mapped_column(Text)
    cover_url: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[str] = mapped_column(Text, default="")  # JSON 字符串
    num_favorites: Mapped[int] = mapped_column(Integer, default=0)
    reported_pages: Mapped[int] = mapped_column(Integer, default=0)
    actual_pages: Mapped[int] = mapped_column(Integer, default=0)
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    downloaded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    subscriptions: Mapped[list["SubscriptionGallery"]] = relationship(back_populates="gallery", lazy="selectin")


class SubscriptionGallery(Base):
    __tablename__ = "subscription_gallery"

    subscription_id: Mapped[int] = mapped_column(ForeignKey("subscription.id"), primary_key=True)
    gallery_id: Mapped[str] = mapped_column(ForeignKey("gallery.id"), primary_key=True)

    subscription: Mapped[Subscription] = relationship(back_populates="galleries")
    gallery: Mapped[Gallery] = relationship(back_populates="subscriptions")


class Page(Base):
    __tablename__ = "page"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    gallery_id: Mapped[str] = mapped_column(ForeignKey("gallery.id"))
    page_index: Mapped[int] = mapped_column(Integer)
    page_native_id: Mapped[str] = mapped_column(String(256))


class SourceCredential(Base):
    __tablename__ = "source_credential"

    source_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    encrypted_value: Mapped[str] = mapped_column(Text)


class SystemLog(Base):
    __tablename__ = "system_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    level: Mapped[str] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text)
