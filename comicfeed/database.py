from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from comicfeed.models import Base

_engine = None
_sessionmaker = None


def init_db(path: str):
    global _engine, _sessionmaker
    _engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)


def get_session() -> AsyncSession:
    return _sessionmaker()


async def create_tables():
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
