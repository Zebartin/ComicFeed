from sqlalchemy import select

from comicfeed.database import get_session
from comicfeed.models import GlobalSetting


async def get_setting(key: str, default: str | None = None) -> str | None:
    async with get_session() as session:
        result = await session.get(GlobalSetting, key)
        return result.value if result else default


async def get_source_proxy(source_key: str) -> str | None:
    """获取源的代理地址：每源优先（- 表示不走代理），全局兜底。"""
    per = await get_setting(f"proxy_{source_key}", "") or ""
    if per == "-":
        return None  # 明确不用代理
    if per:
        return per
    g = await get_setting("proxy", "") or ""
    return g or None


async def set_setting(key: str, value: str):
    async with get_session() as session:
        setting = await session.get(GlobalSetting, key)
        if setting:
            setting.value = value
        else:
            session.add(GlobalSetting(key=key, value=value))
        await session.commit()
