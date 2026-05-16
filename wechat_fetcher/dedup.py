"""标题+URL 去重索引，按 biz 隔离存储于 data/index/dedup_index.json。"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class DedupIndex:
    def __init__(self, root_dir: str = None):
        if root_dir is None:
            root_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
        self._root = Path(root_dir)
        self._index_path = self._root / "index" / "dedup_index.json"
        self._data = self._load()

    def is_duplicate(self, biz: str, title: str, url: str) -> bool:
        entry = self._data.get(biz, {})
        if title and title in entry.get("titles", {}):
            return True
        if url and url in entry.get("urls", {}):
            return True
        return False

    def mark_seen(self, biz: str, title: str, url: str) -> None:
        entry = self._data.setdefault(biz, {"titles": {}, "urls": {}})
        now = datetime.now(timezone.utc).isoformat()
        if title:
            entry["titles"][title] = now
        if url:
            entry["urls"][url] = now
        self._save()

    def stats(self, biz: Optional[str] = None) -> dict:
        if biz:
            entry = self._data.get(biz, {})
            return {
                "biz": biz,
                "titles": len(entry.get("titles", {})),
                "urls": len(entry.get("urls", {})),
            }
        total_titles = sum(len(v.get("titles", {})) for v in self._data.values())
        total_urls = sum(len(v.get("urls", {})) for v in self._data.values())
        return {
            "total_titles": total_titles,
            "total_urls": total_urls,
            "accounts": len(self._data),
        }

    def _load(self) -> dict:
        if not self._index_path.exists():
            return {}
        try:
            with open(self._index_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}

    def _save(self) -> None:
        self._index_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = None, None
        try:
            import tempfile
            fd, tmp = tempfile.mkstemp(dir=str(self._index_path.parent), suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self._index_path)
        finally:
            if tmp and os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
