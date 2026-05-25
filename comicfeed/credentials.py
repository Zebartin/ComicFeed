from cryptography.fernet import Fernet
from sqlalchemy import select

from comicfeed.database import get_session
from comicfeed.models import SourceCredential

_FERNET: Fernet | None = None


def init(key: str):
    global _FERNET
    _FERNET = Fernet(key.encode("utf-8") if isinstance(key, str) else key)


def encrypt_value(value: str) -> str:
    assert _FERNET is not None, "credentials.init() 未调用"
    return _FERNET.encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_value(encrypted: str) -> str:
    assert _FERNET is not None, "credentials.init() 未调用"
    return _FERNET.decrypt(encrypted.encode("utf-8")).decode("utf-8")


async def get_source_credentials(source_key: str) -> dict[str, str]:
    from comicfeed.config import get_source_config
    cfg = await get_source_config(source_key)
    if cfg:
        return {k: v for k, v in cfg.items() if k != "proxy" and v}
    # 回退旧格式
    async with get_session() as session:
        stmt = select(SourceCredential).where(SourceCredential.source_key == source_key)
        result = await session.execute(stmt)
        creds = result.scalars().all()
        return {c.key: decrypt_value(c.encrypted_value) for c in creds}
