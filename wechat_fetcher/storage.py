"""认证参数持久化，按 biz 拆分存储于 data/params/<biz>.json。"""

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class ParamStore:
    def __init__(self, root_dir: str = None):
        if root_dir is None:
            root_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
        self._params_dir = Path(root_dir) / "params"

    def _ensure_dir(self):
        self._params_dir.mkdir(parents=True, exist_ok=True)

    def _biz_path(self, biz: str) -> Path:
        safe = biz.replace("/", "_").replace("\\", "_")
        return self._params_dir / f"{safe}.json"

    def save(self, biz: str, uin: str, key: str,
             pass_ticket: str = "", appmsg_token: str = "",
             cookie: str = "") -> None:
        self._ensure_dir()
        entry = self._load_biz(biz)
        entry.update({
            "__biz": biz,
            "uin": uin,
            "key": key,
            "extracted_at": datetime.now(timezone.utc).isoformat(),
        })
        if pass_ticket:
            entry["pass_ticket"] = pass_ticket
        if appmsg_token:
            entry["appmsg_token"] = appmsg_token
        if cookie:
            entry["cookie"] = cookie

        path = self._biz_path(biz)
        fd, tmp = tempfile.mkstemp(dir=str(self._params_dir), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(entry, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def load(self, biz: str) -> Optional[dict]:
        path = self._biz_path(biz)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return None

    def list_accounts(self) -> list[dict]:
        self._ensure_dir()
        accounts = []
        for f in sorted(self._params_dir.glob("*.json")):
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                accounts.append({
                    "__biz": data.get("__biz", f.stem),
                    "extracted_at": data.get("extracted_at"),
                })
            except (json.JSONDecodeError, IOError):
                continue
        return accounts

    def delete(self, biz: str) -> bool:
        path = self._biz_path(biz)
        if path.exists():
            path.unlink()
            return True
        return False

    def _load_biz(self, biz: str) -> dict:
        path = self._biz_path(biz)
        if not path.exists():
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
