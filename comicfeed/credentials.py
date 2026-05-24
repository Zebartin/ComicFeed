from cryptography.fernet import Fernet
from sqlalchemy import select

from comicfeed.database import get_session
from comicfeed.models import SourceCredential

_FERNET: Fernet | None = None


async def _get_fernet() -> Fernet:
    global _FERNET
    if _FERNET is not None:
        return _FERNET

    from comicfeed.config import get_setting, set_setting
    key = await get_setting("_fernet_key", "")
    if not key:
        key = Fernet.generate_key().decode("utf-8")
        await set_setting("_fernet_key", key)
    _FERNET = Fernet(key.encode("utf-8"))
    return _FERNET


async def encrypt_value(value: str) -> str:
    f = await _get_fernet()
    return f.encrypt(value.encode("utf-8")).decode("utf-8")


async def decrypt_value(encrypted: str) -> str:
    f = await _get_fernet()
    return f.decrypt(encrypted.encode("utf-8")).decode("utf-8")


async def get_source_credentials(source_key: str) -> dict[str, str]:
    """从数据库读取并解密指定源的凭证。"""
    async with get_session() as session:
        stmt = select(SourceCredential).where(SourceCredential.source_key == source_key)
        result = await session.execute(stmt)
        creds = result.scalars().all()
        return {c.key: await decrypt_value(c.encrypted_value) for c in creds}
