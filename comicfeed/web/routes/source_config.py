"""源配置 API：每个源的配置存储为一个加密 JSON blob。"""
import json

from fastapi import APIRouter
from pydantic import BaseModel

from comicfeed.credentials import decrypt_value, encrypt_value
from comicfeed.database import get_session
from comicfeed.models import SourceCredential

router = APIRouter(prefix="/api/sources", tags=["sources"])

_CONFIG_KEY = "_config"


@router.get("/{source_key}/config")
async def get_config(source_key: str):
    async with get_session() as session:
        cred = await session.get(SourceCredential, (source_key, _CONFIG_KEY))
        if cred:
            return json.loads(decrypt_value(cred.encrypted_value))
        return {}


@router.put("/{source_key}/config")
async def set_config(source_key: str, data: dict):
    encrypted = encrypt_value(json.dumps(data, ensure_ascii=False))
    async with get_session() as session:
        cred = await session.get(SourceCredential, (source_key, _CONFIG_KEY))
        if cred:
            cred.encrypted_value = encrypted
        else:
            session.add(SourceCredential(source_key=source_key, key=_CONFIG_KEY, encrypted_value=encrypted))
        await session.commit()
    return {"status": "ok"}
