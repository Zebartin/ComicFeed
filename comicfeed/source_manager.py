import importlib.util
import sys
from pathlib import Path

from comicfeed.sources.base import BaseSource


class SourceManager:
    REQUIRED_ATTRS = ("key", "name", "version", "domains")

    def validate_source(self, source_cls: type[BaseSource]) -> bool:
        if not issubclass(source_cls, BaseSource):
            return False
        for attr in self.REQUIRED_ATTRS:
            if not getattr(source_cls, attr, None):
                return False
        return True

    def load_sources(self, directory: str) -> list[BaseSource]:
        sources = []
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
                    sources.append(attr())
        return sources
