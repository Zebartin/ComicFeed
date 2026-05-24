import pytest

from comicfeed.source_manager import SourceManager
from comicfeed.sources.base import AuthSchema, BaseSource


class _ValidSource(BaseSource):
    key = "test-source"
    name = "Test Source"
    version = "1.0.0"
    domains = ["test.com"]
    auth_schema = AuthSchema.NONE

    async def search(self, query: str, page: int, sort: str = "date"):
        raise NotImplementedError

    async def get_gallery(self, gallery_id: str):
        raise NotImplementedError

    async def download_pages(self, gallery_id: str, page_range: slice):
        raise NotImplementedError

    async def check_updates(self, gallery_id: str, last_known: dict):
        raise NotImplementedError

    def parse_url(self, url: str) -> str | None:
        return None


class _NoKeySource(BaseSource):
    name = "No Key"
    version = "1.0.0"
    domains = ["test.com"]
    auth_schema = AuthSchema.NONE


async def test_valid_source_passes_validation():
    """合法的源类通过验证。"""
    manager = SourceManager()
    result = manager.validate_source(_ValidSource)
    assert result is True


async def test_source_missing_key_fails_validation():
    """缺少 key 的源验证失败。"""
    manager = SourceManager()
    result = manager.validate_source(_NoKeySource)
    assert result is False


async def test_load_sources_from_directory(tmp_path):
    """从目录扫描并加载合法源。"""
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    (source_dir / "test_plugin.py").write_text("""
from comicfeed.sources.base import AuthSchema, BaseSource

class TestPlugin(BaseSource):
    key = "test-plugin"
    name = "Test Plugin"
    version = "0.1.0"
    domains = ["plugin.com"]
    auth_schema = AuthSchema.NONE

    async def search(self, query, page): pass
    async def get_gallery(self, gallery_id): pass
    async def download_pages(self, gallery_id, page_range): pass
    async def check_updates(self, gallery_id, last_known): pass
""", encoding="utf-8")

    manager = SourceManager()
    keys = manager.load_sources(str(source_dir))
    assert len(keys) == 1
    source = manager.get_source("test-plugin")
    assert source is not None
    assert source.key == "test-plugin"
