from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto


class AuthSchema(Enum):
    NONE = auto()
    COOKIE = auto()
    USERNAME_PASSWORD = auto()
    TOKEN = auto()


@dataclass
class GallerySummary:
    native_id: str
    title: str
    cover_url: str
    page_count: int


@dataclass
class SearchResult:
    items: list[GallerySummary] = field(default_factory=list)
    total_pages: int = 0
    current_page: int = 1


@dataclass
class GalleryDetail:
    native_id: str
    title: str
    cover_url: str
    web_url: str = ""
    page_urls: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    reported_pages: int = 0
    num_favorites: int = 0


@dataclass
class UpdateResult:
    has_updates: bool = False
    new_page_ids: list[str] = field(default_factory=list)
    new_gallery_id: str | None = None


class BaseSource(ABC):
    key: str
    name: str
    version: str
    domains: list[str]
    auth_schema: AuthSchema = AuthSchema.NONE
    proxy: str | None = None
    credentials: dict[str, str]

    def __init__(self, proxy: str | None = None, credentials: dict[str, str] | None = None):
        self.proxy = proxy
        self.credentials = credentials or {}

    @abstractmethod
    async def search(self, query: str, page: int, sort: str = "date") -> SearchResult: ...

    @abstractmethod
    async def get_gallery(self, gallery_id: str) -> GalleryDetail: ...

    @abstractmethod
    async def download_pages(self, gallery_id: str, page_range: slice) -> list[bytes]: ...

    @abstractmethod
    async def check_updates(self, gallery_id: str, last_known: dict) -> UpdateResult: ...

    def parse_url(self, url: str) -> str | None:
        return None

    async def resolve_domain(self) -> list[str]:
        return self.domains
