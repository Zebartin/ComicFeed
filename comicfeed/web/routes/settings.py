from fastapi import APIRouter

from comicfeed.config import get_setting, set_setting

router = APIRouter(prefix="/api/settings", tags=["settings"])

DEFAULTS = {
    "check_interval": "10",
    "download_path": "",
    "global_concurrency": "5",
    "komga_url": "",
    "komga_api_key": "",
    "komga_library_id": "",
    "smtp_host": "",
    "smtp_port": "587",
    "smtp_user": "",
    "smtp_password": "",
    "webhook_url": "",
    "auth_username": "admin",
    "auth_password": "",
}


@router.get("")
async def list_settings():
    result = {}
    for key, default in DEFAULTS.items():
        result[key] = await get_setting(key, default)
    return result


@router.put("/{key}")
async def update_setting(key: str, value: str = ""):
    await set_setting(key, value)
    return {"key": key, "value": value}
