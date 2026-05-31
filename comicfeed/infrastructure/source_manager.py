import importlib.util
import sys
from pathlib import Path

from comicfeed.sources.base import BaseSource


class SourceManager:
    REQUIRED_ATTRS = ("key", "name", "version", "domains")

    def __init__(self):
        self._classes: dict[str, type[BaseSource]] = {}
        self._instances: dict[str, BaseSource] = {}

    def validate_source(self, source_cls: type[BaseSource]) -> bool:
        if not issubclass(source_cls, BaseSource):
            return False
        for attr in self.REQUIRED_ATTRS:
            if not getattr(source_cls, attr, None):
                return False
        return True

    def list_sources(self) -> list[BaseSource]:
        """返回所有已加载源的实例（不含 credentials）。"""
        return list(self._instances.values())

    def get_source(self, key: str, credentials: dict | None = None, proxy: str | None = None) -> BaseSource | None:
        cls = self._classes.get(key)
        if cls is None:
            return None
        return cls(credentials=credentials or {}, proxy=proxy or None)

    def get_source_cls(self, key: str) -> type[BaseSource] | None:
        return self._classes.get(key)

    def load_sources(self, directory: str) -> list:
        results = []
        for f in Path(directory).glob("*.py"):
            if f.name.startswith("_"):
                continue
            module_name = f.stem
            spec = importlib.util.spec_from_file_location(module_name, f)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if not isinstance(attr, type) or not issubclass(attr, BaseSource) or attr is BaseSource:
                    continue
                if self.validate_source(attr):
                    self._classes[attr.key] = attr
                    self._instances[attr.key] = attr()
                    results.append(attr.key)
        return results
