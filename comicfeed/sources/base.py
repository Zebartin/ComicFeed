from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto


class AuthSchema(Enum):
    NONE = auto()
    COOKIE = auto()
    USERNAME_PASSWORD = auto()
    TOKEN = auto()


@dataclass
class GalleryDetail:
    native_id: str
    title: str
    cover_url: str
    web_url: str = ""
    page_urls: list[str] = field(default_factory=list)
    page_native_ids: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    reported_pages: int = 0
    num_favorites: int = 0


@dataclass
class GallerySummary:
    native_id: str
    title: str
    cover_url: str
    web_url: str = ""
    page_count: int = 0
    num_favorites: int = 0
    tag_ids: list[int] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    new_page_ids: list[str] = field(default_factory=list)  # 增量更新：仅新增的 page ID
    replaces_native_id: str = ""  # newer version：被替换的旧画廊 native_id
    detail: GalleryDetail | None = None  # check_updates 预取的完整 detail


@dataclass
class SearchResult:
    items: list[GallerySummary] = field(default_factory=list)
    total_pages: int = 0
    current_page: int = 1
    next_url: str = ""  # 游标制翻页（exhentai 用）


@dataclass
class UpdateResult:
    has_updates: bool = False
    gallery: GallerySummary | None = None


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

    def get_config_schema(self) -> list[dict]:
        """返回源的自定义配置项列表，WebUI 据此渲染表单。
        每项: {key, label, type: 'text'|'textarea'|'password', credential: bool, placeholder, hint}
        credential=True 的字段存入加密凭证表，其余存入全局设置表。
        """
        return []

    def get_sort_options(self) -> list[dict]:
        """返回本源支持的排序选项: [{value, label}]。空列表表示无排序支持。"""
        return []

    @abstractmethod
    async def search(self, query: str, page: int, sort: str = "date") -> SearchResult: ...

    @abstractmethod
    async def get_gallery(self, gallery_id: str, gallery_url: str = "") -> GalleryDetail: ...

    @abstractmethod
    async def download_pages(self, gallery_id: str, page_range: slice, gallery_url: str = "", detail: GalleryDetail | None = None) -> list[bytes]: ...

    @abstractmethod
    async def check_updates(self, gallery_id: str, last_known: dict, gallery_url: str = "") -> UpdateResult: ...

    def parse_url(self, url: str) -> str | None:
        return None

    async def resolve_domain(self) -> list[str]:
        return self.domains
