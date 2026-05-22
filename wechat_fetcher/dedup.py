"""标题+URL 去重索引，按公众号名称分子目录存储于数据目录/accounts/<account_name>/dedup_index.json。"""

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from wechat_fetcher.config import get_config


def sanitize_dirname(name: str, max_length: int = 50) -> str:
    """将名称转换为安全的目录名。"""
    if not name:
        return "unknown"
    invalid_chars = r'[<>:"/\\|?*]'
    name = re.sub(invalid_chars, "_", name)
    name = name.strip().strip(".")
    if len(name) > max_length:
        name = name[:max_length]
    if not name:
        return "unknown"
    return name


class DedupIndex:
    """按公众号名称分子目录存储去重索引。"""

    def __init__(self, root_dir: str = None):
        if root_dir is None:
            root_dir = str(get_config().data_dir)
        self._root = Path(root_dir)
        self._accounts_dir = self._root / "accounts"
        self._ensure_dir()

    def _ensure_dir(self):
        self._accounts_dir.mkdir(parents=True, exist_ok=True)

    def _get_account_dir(self, account_name: str) -> Path:
        """获取公众号对应的目录路径。"""
        safe_name = sanitize_dirname(account_name)
        return self._accounts_dir / safe_name

    def _index_path(self, account_name: str) -> Path:
        """获取去重索引文件路径。"""
        return self._get_account_dir(account_name) / "dedup_index.json"

    def _load(self, account_name: str) -> dict:
        """加载指定公众号的去重索引。"""
        path = self._index_path(account_name)
        if not path.exists():
            return {"titles": {}, "urls": {}}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {"titles": {}, "urls": {}}

    def _save(self, account_name: str, data: dict) -> None:
        """保存指定公众号的去重索引。"""
        path = self._index_path(account_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = None, None
        try:
            import tempfile
            fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        finally:
            if tmp and os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

    def is_duplicate(self, account_name: str, title: str, url: str) -> bool:
        """检查是否为重复文章。

        Args:
            account_name: 公众号名称
            title: 文章标题
            url: 文章URL
        """
        if not account_name:
            # 如果没有名称，无法去重，返回 False
            return False
        entry = self._load(account_name)
        if title and title in entry.get("titles", {}):
            return True
        if url and url in entry.get("urls", {}):
            return True
        return False

    def mark_seen(self, account_name: str, title: str, url: str) -> None:
        """标记文章已下载。

        Args:
            account_name: 公众号名称
            title: 文章标题
            url: 文章URL
        """
        if not account_name:
            return
        entry = self._load(account_name)
        now = datetime.now(timezone.utc).isoformat()
        if title:
            entry["titles"][title] = now
        if url:
            entry["urls"][url] = now
        self._save(account_name, entry)

    def stats(self, account_name: Optional[str] = None) -> dict:
        """获取去重统计信息。

        Args:
            account_name: 公众号名称，为 None 时返回所有账号统计
        """
        if account_name:
            entry = self._load(account_name)
            return {
                "name": account_name,
                "titles": len(entry.get("titles", {})),
                "urls": len(entry.get("urls", {})),
            }

        # 统计所有账号
        total_titles = 0
        total_urls = 0
        accounts = 0

        for account_dir in self._accounts_dir.iterdir():
            if account_dir.is_dir():
                index_path = account_dir / "dedup_index.json"
                if index_path.exists():
                    try:
                        with open(index_path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        total_titles += len(data.get("titles", {}))
                        total_urls += len(data.get("urls", {}))
                        accounts += 1
                    except (json.JSONDecodeError, IOError):
                        continue

        return {
            "total_titles": total_titles,
            "total_urls": total_urls,
            "accounts": accounts,
        }

    def list_accounts(self) -> list[dict]:
        """列出所有有去重索引的账号。"""
        accounts = []
        for account_dir in sorted(self._accounts_dir.iterdir()):
            if account_dir.is_dir():
                index_path = account_dir / "dedup_index.json"
                if index_path.exists():
                    try:
                        with open(index_path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        accounts.append({
                            "name": account_dir.name,
                            "titles": len(data.get("titles", {})),
                            "urls": len(data.get("urls", {})),
                        })
                    except (json.JSONDecodeError, IOError):
                        continue
        return accounts
