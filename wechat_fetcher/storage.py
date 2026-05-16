import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class ParamStore:
    """Persist extracted WeChat params to a JSON file."""

    def __init__(self, path: str = None):
        if path is None:
            path = os.path.join(os.path.expanduser("~"), ".wechat_fetcher", "params.json")
        self._path = Path(path)

    def _ensure_dir(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def _read(self) -> dict:
        if not self._path.exists():
            return {}
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}

    def save(self, biz: str, uin: str, key: str,
             pass_ticket: str = "", appmsg_token: str = "",
             cookie: str = "") -> None:
        self._ensure_dir()
        data = self._read()
        entry = {
            "__biz": biz,
            "uin": uin,
            "key": key,
            "extracted_at": datetime.now(timezone.utc).isoformat(),
        }
        if pass_ticket:
            entry["pass_ticket"] = pass_ticket
        if appmsg_token:
            entry["appmsg_token"] = appmsg_token
        if cookie:
            entry["cookie"] = cookie
        data[biz] = entry
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self._path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def load(self, biz: str = None) -> Optional[dict]:
        data = self._read()
        if biz is None:
            return data
        return data.get(biz)

    def list_accounts(self) -> list[dict]:
        data = self._read()
        return [
            {"__biz": biz, "extracted_at": v.get("extracted_at")}
            for biz, v in data.items()
        ]

    def delete(self, biz: str) -> bool:
        data = self._read()
        if biz in data:
            del data[biz]
            self._ensure_dir()
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        return False
