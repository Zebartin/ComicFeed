from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum, auto


class AuthSchema(Enum):
    NONE = auto()
    COOKIE = auto()
    USERNAME_PASSWORD = auto()
    TOKEN = auto()


class BaseSource(ABC):
    key: str
    name: str
    version: str
    domains: list[str]
    auth_schema: AuthSchema = AuthSchema.NONE

    @abstractmethod
    async def search(self, query: str, page: int): ...

    @abstractmethod
    async def get_gallery(self, gallery_id: str): ...

    @abstractmethod
    async def download_pages(self, gallery_id: str, page_range: slice): ...

    @abstractmethod
    async def check_updates(self, gallery_id: str, last_known: dict): ...

    def parse_url(self, url: str) -> str | None:
        return None

    async def resolve_domain(self) -> list[str]:
        return self.domains
