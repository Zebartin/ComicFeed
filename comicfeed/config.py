from sqlalchemy import select

from comicfeed.database import get_session
from comicfeed.models import GlobalSetting


async def get_setting(key: str, default: str | None = None) -> str | None:
    async with get_session() as session:
        result = await session.get(GlobalSetting, key)
        return result.value if result else default


async def get_source_config(source_key: str) -> dict:
    """读取源的完整配置 JSON。"""
    import json
    from comicfeed.credentials import decrypt_value
    from comicfeed.database import get_session
    from comicfeed.models import SourceCredential
    async with get_session() as s:
        cred = await s.get(SourceCredential, (source_key, "_config"))
        if cred:
            return json.loads(decrypt_value(cred.encrypted_value))
        return {}


async def get_source_proxy(source_key: str) -> str | None:
    """获取源的代理地址：每源优先（- 表示不走代理），全局兜底。"""
    cfg = await get_source_config(source_key)
    per = cfg.get("proxy", "") or ""
    if per == "-":
        return None
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
