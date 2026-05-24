import asyncio
import os
import sys

import pytest

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "integration: tests that require network access"
    )


@pytest.fixture
def nhentai_credentials():
    """从环境变量 NHENTAI_COOKIES 读取 nhentai 凭证。

    格式: csrftoken=xxx; cf_clearance=yyy
    """
    raw = os.environ.get("NHENTAI_COOKIES", "")
    if not raw:
        pytest.skip("NHENTAI_COOKIES not set")
    cookies = {}
    for part in raw.split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            cookies[k.strip()] = v.strip()
    return cookies
