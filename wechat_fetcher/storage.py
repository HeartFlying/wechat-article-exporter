"""认证参数持久化，按公众号名称分子目录存储于数据目录/accounts/<account_name>/params.json。"""

import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import requests

from wechat_fetcher.config import get_config


class ParamStatus(Enum):
    """参数状态枚举。"""
    VALID = "valid"           # 有效
    EXPIRING_SOON = "expiring_soon"  # 即将过期（1小时内）
    EXPIRED = "expired"       # 已过期
    NOT_FOUND = "not_found"   # 未找到


@dataclass
class ParamHealth:
    """参数健康状态信息。"""
    status: ParamStatus
    biz: str
    name: str
    extracted_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    age_seconds: float = 0.0
    remaining_seconds: float = 0.0
    message: str = ""

    @property
    def is_valid(self) -> bool:
        return self.status == ParamStatus.VALID

    @property
    def is_expired(self) -> bool:
        return self.status == ParamStatus.EXPIRED

    @property
    def needs_refresh(self) -> bool:
        return self.status in (ParamStatus.EXPIRED, ParamStatus.EXPIRING_SOON)


def sanitize_dirname(name: str, max_length: int = 50) -> str:
    """将名称转换为安全的目录名。"""
    if not name:
        return "unknown"
    # 移除或替换非法字符
    invalid_chars = r'[<>:"/\\|?*]'
    name = re.sub(invalid_chars, "_", name)
    # 移除首尾空格和点
    name = name.strip().strip(".")
    # 限制长度
    if len(name) > max_length:
        name = name[:max_length]
    # 如果为空，使用默认值
    if not name:
        return "unknown"
    return name


class ParamStore:
    """按公众号名称分子目录存储认证参数。"""

    # API 验证相关配置
    API_URL = "https://mp.weixin.qq.com/mp/profile_ext"
    KEY_EXPIRED_CODES = {-3, -1, 200013, 40001, 40030}
    API_VERIFY_TIMEOUT = 10  # API 验证超时时间（秒）
    API_VERIFY_CACHE_SECONDS = 60  # API 验证结果缓存时间（秒）

    def __init__(self, root_dir: str = None):
        if root_dir is None:
            root_dir = str(get_config().data_dir)
        self._accounts_dir = Path(root_dir) / "accounts"
        self._ensure_dir()
        # API 验证结果缓存: {biz: (验证结果, 验证时间)}
        self._api_verify_cache: dict[str, tuple[bool, datetime]] = {}

    def _ensure_dir(self):
        self._accounts_dir.mkdir(parents=True, exist_ok=True)

    def _get_account_dir(self, account_name: str) -> Path:
        """获取公众号对应的目录路径。"""
        safe_name = sanitize_dirname(account_name)
        return self._accounts_dir / safe_name

    def _params_path(self, account_name: str) -> Path:
        """获取参数文件路径。"""
        return self._get_account_dir(account_name) / "params.json"

    def save(self, biz: str, uin: str, key: str,
             pass_ticket: str = "", appmsg_token: str = "",
             cookie: str = "", name: str = "") -> None:
        """保存认证参数。

        Args:
            biz: 公众号的 __biz
            uin: 用户 uin
            key: 认证 key
            pass_ticket: pass_ticket
            appmsg_token: appmsg_token
            cookie: cookie
            name: 公众号名称（用于确定存储目录）
        """
        # 如果没有提供名称，尝试从已有记录获取
        if not name:
            existing = self._find_by_biz(biz)
            if existing:
                name = existing.get("name", "")
        if not name:
            name = biz  # 兜底使用 biz 作为目录名

        self._ensure_dir()
        entry = self._load_by_name(name)
        entry.update({
            "__biz": biz,
            "uin": uin,
            "key": key,
            "name": name,
            "extracted_at": datetime.now(timezone.utc).isoformat(),
        })
        if pass_ticket:
            entry["pass_ticket"] = pass_ticket
        if appmsg_token:
            entry["appmsg_token"] = appmsg_token
        if cookie:
            entry["cookie"] = cookie

        path = self._params_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(entry, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def update_account_info(self, biz: str, name: str = None) -> None:
        """更新账号的人类可读信息（如公众号名称）。"""
        if not name:
            return
        # 查找该 biz 对应的记录
        existing = self._find_by_biz(biz)
        if existing:
            old_name = existing.get("name", "")
            if old_name and old_name != name:
                # 名称发生变化，需要迁移目录
                self._migrate_account(old_name, name)
            else:
                # 更新现有记录
                entry = self._load_by_name(name)
                entry["name"] = name
                path = self._params_path(name)
                path.parent.mkdir(parents=True, exist_ok=True)
                fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        json.dump(entry, f, ensure_ascii=False, indent=2)
                    os.replace(tmp, path)
                finally:
                    if os.path.exists(tmp):
                        os.unlink(tmp)

    def _migrate_account(self, old_name: str, new_name: str) -> None:
        """迁移账号数据到新的目录。"""
        old_dir = self._get_account_dir(old_name)
        new_dir = self._get_account_dir(new_name)

        if not old_dir.exists():
            return

        # 如果新目录已存在，合并数据
        if new_dir.exists():
            # 移动所有文件
            for item in old_dir.iterdir():
                dest = new_dir / item.name
                if dest.exists():
                    # 如果目标已存在，保留较新的文件
                    if item.stat().st_mtime > dest.stat().st_mtime:
                        import shutil
                        shutil.copy2(item, dest)
                else:
                    import shutil
                    shutil.move(str(item), str(dest))
            # 删除旧目录
            import shutil
            shutil.rmtree(old_dir)
        else:
            # 直接重命名目录
            new_dir.parent.mkdir(parents=True, exist_ok=True)
            old_dir.rename(new_dir)

        # 更新参数文件中的名称
        params_path = new_dir / "params.json"
        if params_path.exists():
            try:
                with open(params_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                data["name"] = new_name
                with open(params_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            except (json.JSONDecodeError, IOError):
                pass

    def _find_by_biz(self, biz: str) -> Optional[dict]:
        """通过 biz 查找账号信息。"""
        for account_dir in self._accounts_dir.iterdir():
            if account_dir.is_dir():
                params_path = account_dir / "params.json"
                if params_path.exists():
                    try:
                        with open(params_path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        if data.get("__biz") == biz:
                            return data
                    except (json.JSONDecodeError, IOError):
                        continue
        return None

    def _load_by_name(self, name: str) -> dict:
        """按名称加载参数。"""
        path = self._params_path(name)
        if not path.exists():
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}

    def load(self, biz: str) -> Optional[dict]:
        """通过 biz 加载参数。"""
        return self._find_by_biz(biz)

    def load_by_name(self, name: str) -> Optional[dict]:
        """通过公众号名称加载参数。"""
        return self._load_by_name(name)

    def list_accounts(self) -> list[dict]:
        """列出所有已存储的账号。"""
        self._ensure_dir()
        accounts = []
        for account_dir in sorted(self._accounts_dir.iterdir()):
            if account_dir.is_dir():
                params_path = account_dir / "params.json"
                if params_path.exists():
                    try:
                        with open(params_path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        accounts.append({
                            "__biz": data.get("__biz", ""),
                            "name": data.get("name", account_dir.name),
                            "extracted_at": data.get("extracted_at"),
                        })
                    except (json.JSONDecodeError, IOError):
                        continue
        return accounts

    def delete(self, name: str) -> bool:
        """删除指定账号的所有数据。"""
        account_dir = self._get_account_dir(name)
        if account_dir.exists():
            import shutil
            shutil.rmtree(account_dir)
            return True
        return False

    def get_account_dir(self, name: str) -> Path:
        """获取公众号的数据目录路径。"""
        return self._get_account_dir(name)

    def _verify_api_validity(self, params: dict) -> tuple[bool, str]:
        """通过调用微信 API 验证参数有效性。

        Args:
            params: 包含 biz, uin, key 等参数的字典

        Returns:
            (是否有效, 消息)
        """
        biz = params.get("__biz", "")
        uin = params.get("uin", "")
        key = params.get("key", "")
        pass_ticket = params.get("pass_ticket", "")
        cookie = params.get("cookie", "")

        if not all([biz, uin, key]):
            return False, "参数不完整，缺少必要字段"

        # 构建 API 请求 URL（只请求1条数据用于验证）
        url = (
            f"{self.API_URL}?action=getmsg"
            f"&__biz={quote(biz, safe='')}"
            f"&f=json"
            f"&offset=0"
            f"&count=1"
            f"&uin={quote(uin, safe='')}"
            f"&key={quote(key, safe='')}"
        )
        if pass_ticket:
            url += f"&pass_ticket={quote(pass_ticket, safe='')}"

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36 "
                "MicroMessenger/7.0.20.1781(0x6700143B) "
                "NetType/WIFI MiniProgramEnv/Windows WindowsWechat"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": f"https://mp.weixin.qq.com/mp/profile_ext?action=home&__biz={biz}&scene=124",
        }
        if cookie:
            headers["Cookie"] = cookie

        try:
            resp = requests.get(url, headers=headers, timeout=self.API_VERIFY_TIMEOUT)
            data = resp.json()

            ret = data.get("base_resp", {}).get("ret", 0)

            if ret == 0:
                return True, "API 验证通过，参数有效"

            if ret in self.KEY_EXPIRED_CODES:
                return False, f"API 返回错误码 {ret}，参数已过期"

            err_msg = data.get("base_resp", {}).get("err_msg", "")
            return False, f"API 返回错误: ret={ret}, msg={err_msg}"

        except requests.exceptions.Timeout:
            return False, "API 验证超时"
        except requests.exceptions.RequestException as e:
            return False, f"API 请求失败: {e}"
        except json.JSONDecodeError:
            return False, "API 返回数据解析失败"

    def _get_cached_api_verify(self, biz: str, params: dict) -> tuple[bool, str]:
        """获取缓存的 API 验证结果，如果过期则重新验证。

        Args:
            biz: 公众号的 __biz
            params: 参数字典

        Returns:
            (是否有效, 消息)
        """
        now = datetime.now(timezone.utc)

        # 检查缓存
        if biz in self._api_verify_cache:
            is_valid, cached_time = self._api_verify_cache[biz]
            cache_age = (now - cached_time).total_seconds()

            # 缓存未过期，直接返回
            if cache_age < self.API_VERIFY_CACHE_SECONDS:
                if is_valid:
                    return True, f"参数有效（缓存，{cache_age:.0f}秒前验证）"
                else:
                    return False, f"参数已过期（缓存，{cache_age:.0f}秒前验证）"

        # 缓存不存在或已过期，重新验证
        is_valid, message = self._verify_api_validity(params)
        self._api_verify_cache[biz] = (is_valid, now)
        return is_valid, message

    def check_health(self, biz: str, use_cache: bool = True) -> ParamHealth:
        """检查指定账号参数的健康状态（基于 API 验证）。

        Args:
            biz: 公众号的 __biz
            use_cache: 是否使用缓存的验证结果（默认 True）

        Returns:
            ParamHealth 对象，包含状态和健康信息
        """
        params = self._find_by_biz(biz)

        if params is None:
            return ParamHealth(
                status=ParamStatus.NOT_FOUND,
                biz=biz,
                name="",
                message="未找到该账号的参数，请先运行 start-proxy 获取"
            )

        name = params.get("name", "")
        extracted_at_str = params.get("extracted_at")

        # 解析提取时间（仅用于信息展示）
        extracted_at = None
        age_seconds = 0.0
        if extracted_at_str:
            try:
                extracted_at = datetime.fromisoformat(extracted_at_str)
                age_seconds = (datetime.now(timezone.utc) - extracted_at).total_seconds()
            except (ValueError, TypeError):
                pass

        # 通过 API 验证参数有效性
        if use_cache:
            is_valid, message = self._get_cached_api_verify(biz, params)
        else:
            is_valid, message = self._verify_api_validity(params)

        if is_valid:
            status = ParamStatus.VALID
        else:
            status = ParamStatus.EXPIRED

        return ParamHealth(
            status=status,
            biz=biz,
            name=name,
            extracted_at=extracted_at,
            expires_at=None,  # 不再基于时间计算过期时间
            age_seconds=age_seconds,
            remaining_seconds=0.0,  # 不再基于时间计算剩余时间
            message=message
        )

    def check_all_health(self) -> list[ParamHealth]:
        """检查所有账号的参数健康状态。

        Returns:
            ParamHealth 对象列表
        """
        results = []
        accounts = self.list_accounts()

        for account in accounts:
            biz = account.get("__biz", "")
            if biz:
                health = self.check_health(biz)
                results.append(health)

        return results

    def get_expired_accounts(self) -> list[ParamHealth]:
        """获取所有参数已过期或即将过期的账号。

        Returns:
            需要刷新的账号健康状态列表
        """
        all_health = self.check_all_health()
        return [h for h in all_health if h.needs_refresh]

    def get_valid_accounts(self) -> list[ParamHealth]:
        """获取所有参数有效的账号。

        Returns:
            有效的账号健康状态列表
        """
        all_health = self.check_all_health()
        return [h for h in all_health if h.is_valid]
