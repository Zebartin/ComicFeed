import asyncio
import sys

import pytest

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def pytest_addoption(parser):
    parser.addoption("--run-live", action="store_true", default=False,
                     help="运行冒烟测试（需网络和凭证）")


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "integration: tests that require network access"
    )
    config.addinivalue_line(
        "markers", "live: 冒烟测试（需 --run-live 参数）"
    )


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--run-live"):
        for item in items:
            if item.get_closest_marker("live"):
                item.add_marker(pytest.mark.skip(
                    reason="使用 --run-live 启动冒烟测试"
                ))

