from sqlalchemy import text
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
        await _migrate(conn)


async def _migrate(conn):
    """简单迁移：自动添加缺失列、删除过时列。"""
    # 删除已知过时列
    _drop_cols = {"page": ["page_index"]}
    for table_name, cols in _drop_cols.items():
        result = await conn.execute(text(f"PRAGMA table_info({table_name})"))
        existing = {row[1] for row in result.fetchall()}
        for col_name in cols:
            if col_name in existing:
                await conn.execute(text(f'ALTER TABLE {table_name} DROP COLUMN "{col_name}"'))

    for table in Base.metadata.sorted_tables:
        # 获取表中已有列
        result = await conn.execute(text(f"PRAGMA table_info({table.name})"))
        rows = result.fetchall()
        existing = {row[1] for row in rows}
        # 对于模型中定义但表中缺失的列，用 ALTER TABLE 添加
        for col in table.columns:
            if col.name not in existing:
                nullable = "NULL" if col.nullable else "NOT NULL"
                default = ""
                if col.default and col.default.arg is not None:
                    if isinstance(col.default.arg, str):
                        default = f" DEFAULT '{col.default.arg}'"
                    else:
                        default = f" DEFAULT {col.default.arg}"
                sql = f'ALTER TABLE {table.name} ADD COLUMN "{col.name}" {col.type} {nullable}{default}'
                await conn.execute(text(sql))
