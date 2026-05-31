"""全局配置 + 凭证加密/读取。config + credentials 合并，消除循环依赖。"""
import json

from cryptography.fernet import Fernet
from sqlalchemy import select

from comicfeed.infrastructure.database import get_session
from comicfeed.models import GlobalSetting, SourceCredential

_FERNET: Fernet | None = None


# --- Global settings ---

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


# --- Fernet crypto ---

def init_crypto(key: str):
    global _FERNET
    _FERNET = Fernet(key.encode("utf-8") if isinstance(key, str) else key)


def encrypt_value(value: str) -> str:
    assert _FERNET is not None, "init_crypto() 未调用"
    return _FERNET.encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_value(encrypted: str) -> str:
    assert _FERNET is not None, "init_crypto() 未调用"
    return _FERNET.decrypt(encrypted.encode("utf-8")).decode("utf-8")


# --- Source config ---

async def get_source_config(source_key: str) -> dict:
    async with get_session() as s:
        cred = await s.get(SourceCredential, (source_key, "_config"))
        if cred:
            return json.loads(decrypt_value(cred.encrypted_value))
        return {}


async def get_source_proxy(source_key: str) -> str | None:
    cfg = await get_source_config(source_key)
    per = cfg.get("proxy", "") or ""
    if per == "-":
        return None
    if per:
        return per
    g = await get_setting("proxy", "") or ""
    return g or None


# --- Source credentials ---

async def get_source_credentials(source_key: str) -> dict[str, str]:
    cfg = await get_source_config(source_key)
    if cfg:
        return {k: v for k, v in cfg.items() if k != "proxy" and v}
    async with get_session() as session:
        stmt = select(SourceCredential).where(SourceCredential.source_key == source_key)
        result = await session.execute(stmt)
        creds = result.scalars().all()
        return {c.key: decrypt_value(c.encrypted_value) for c in creds}
