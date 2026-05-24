import re

from comicfeed.sources.base import AuthSchema, BaseSource


class NhentaiSource(BaseSource):
    key = "nhentai"
    name = "nHentai"
    version = "0.1.0"
    domains = ["nhentai.net"]
    auth_schema = AuthSchema.NONE

    _URL_PATTERN = re.compile(r"https?://(?:www\.)?nhentai\.net/g/(\d+)")

    def parse_url(self, url: str) -> str | None:
        m = self._URL_PATTERN.match(url)
        if m:
            return f"nhentai:{m.group(1)}"
        return None

    async def search(self, query: str, page: int):
        raise NotImplementedError

    async def get_gallery(self, gallery_id: str):
        raise NotImplementedError

    async def download_pages(self, gallery_id: str, page_range: slice):
        raise NotImplementedError

    async def check_updates(self, gallery_id: str, last_known: dict):
        raise NotImplementedError
