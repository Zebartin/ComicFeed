import json
from pathlib import Path


class TagTranslator:
    def __init__(self, db_data: str | None = None, db_path: str | None = None):
        self._namespaces: dict[str, str] = {}
        self._tags: dict[str, str] = {}
        if db_data:
            self._load_from_string(db_data)
        elif db_path:
            self._load_from_file(db_path)

    def _load_from_string(self, data: str):
        db = json.loads(data)
        self._namespaces = db.get("namespaces", {})
        self._tags = db.get("tags", {})

    def _load_from_file(self, path: str):
        with open(path, "r", encoding="utf-8") as f:
            self._load_from_string(f.read())

    @classmethod
    def from_default_db(cls) -> "TagTranslator":
        default_path = Path(__file__).parent / "data" / "eh_tags.json"
        if default_path.exists():
            return cls(db_path=str(default_path))
        return cls()

    def translate(self, tag_name: str) -> str:
        return self._tags.get(tag_name, tag_name)

    def translate_tag(self, namespace: str, tag_name: str) -> str:
        ns_cn = self._namespaces.get(namespace, namespace)
        tag_cn = self._tags.get(tag_name, tag_name)
        return f"{ns_cn}：{tag_cn}"
