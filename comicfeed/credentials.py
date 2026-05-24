import base64
import os

from cryptography.fernet import Fernet
from sqlalchemy import select

from comicfeed.database import get_session
from comicfeed.models import SourceCredential

_KEY = os.environ.get("COMICFEED_SECRET_KEY")
if _KEY:
    _FERNET = Fernet(base64.urlsafe_b64encode(_KEY.encode("utf-8")[:32].ljust(32, b"\x00")))
else:
    _FERNET = None


def _get_fernet() -> Fernet:
    global _FERNET
    if _FERNET is None:
        _FERNET = Fernet(Fernet.generate_key())
    return _FERNET


def encrypt_value(value: str) -> str:
    return _get_fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_value(encrypted: str) -> str:
    return _get_fernet().decrypt(encrypted.encode("utf-8")).decode("utf-8")


async def get_source_credentials(source_key: str) -> dict[str, str]:
    """从数据库读取并解密指定源的凭证。"""
    async with get_session() as session:
        stmt = select(SourceCredential).where(SourceCredential.source_key == source_key)
        result = await session.execute(stmt)
        creds = result.scalars().all()
        return {c.key: decrypt_value(c.encrypted_value) for c in creds}
