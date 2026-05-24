from comicfeed.database import create_tables, get_session, init_db
from comicfeed.models import SourceCredential
from comicfeed.credentials import encrypt_value, get_source_credentials


async def test_save_and_load_credentials():
    """凭证加密存储后可解密读取。"""
    init_db(":memory:")
    await create_tables()

    # 存入加密凭证
    async with get_session() as session:
        cred = SourceCredential(
            source_key="nhentai",
            key="cf_clearance",
            encrypted_value=await encrypt_value("test-clearance-cookie"),
        )
        session.add(cred)
        await session.commit()

    # 读取并解密
    creds = await get_source_credentials("nhentai")
    assert creds["cf_clearance"] == "test-clearance-cookie"


async def test_empty_credentials():
    """没有凭证的源返回空 dict。"""
    init_db(":memory:")
    await create_tables()
    creds = await get_source_credentials("nhentai")
    assert creds == {}


async def test_multiple_credentials_per_source():
    """一个源可以有多条凭证。"""
    init_db(":memory:")
    await create_tables()

    async with get_session() as session:
        session.add(SourceCredential(source_key="exhentai", key="ipb_member_id", encrypted_value=await encrypt_value("12345")))
        session.add(SourceCredential(source_key="exhentai", key="ipb_pass_hash", encrypted_value=await encrypt_value("abcdef")))
        await session.commit()

    creds = await get_source_credentials("exhentai")
    assert creds["ipb_member_id"] == "12345"
    assert creds["ipb_pass_hash"] == "abcdef"
