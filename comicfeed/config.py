from sqlalchemy import select

from comicfeed.database import get_session
from comicfeed.models import GlobalSetting


async def get_setting(key: str, default: str | None = None) -> str | None:
    async with get_session() as session:
        result = await session.get(GlobalSetting, key)
        return result.value if result else default


async def set_setting(key: str, value: str):
    async with get_session() as session:
        setting = await session.get(GlobalSetting, key)
        if setting:
            setting.value = value
        else:
            session.add(GlobalSetting(key=key, value=value))
        await session.commit()
