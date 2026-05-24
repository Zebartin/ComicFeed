from fastapi import APIRouter
from pydantic import BaseModel

from comicfeed.credentials import encrypt_value, get_source_credentials
from comicfeed.database import get_session
from comicfeed.models import SourceCredential

router = APIRouter(prefix="/api/credentials", tags=["credentials"])


class CredentialSet(BaseModel):
    credentials: dict[str, str]  # key → value


@router.get("/{source_key}")
async def list_credentials(source_key: str):
    creds = await get_source_credentials(source_key)
    return {"source_key": source_key, "credentials": creds}


@router.put("/{source_key}")
async def set_credentials(source_key: str, data: CredentialSet):
    async with get_session() as session:
        # 删除旧凭证
        from sqlalchemy import delete
        await session.execute(
            delete(SourceCredential).where(SourceCredential.source_key == source_key)
        )
        # 写入新凭证
        for key, value in data.credentials.items():
            session.add(SourceCredential(
                source_key=source_key,
                key=key,
                encrypted_value=encrypt_value(value),
            ))
        await session.commit()
    return {"status": "ok", "count": len(data.credentials)}
