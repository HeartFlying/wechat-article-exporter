import json
import random
import time
from datetime import datetime, timedelta, timezone
from typing import Callable, List, Optional, Tuple
from urllib.parse import quote

import requests


class KeyExpiredError(Exception):
    pass


class WeChatArticleFetcher:
    API_URL = "https://mp.weixin.qq.com/mp/profile_ext"
    ARTICLE_BASE = "https://mp.weixin.qq.com"
    PAGE_SIZE = 10
    DEFAULT_DELAY = (3.0, 6.0)
    RATE_LIMIT_BACKOFF = 60.0
    MAX_RETRIES = 3
    MAX_PAGES = 100
    KEY_EXPIRED_CODES = {-3, -1, 200013, 40001, 40030}

    def __init__(self, biz: str, uin: str, key: str,
                 pass_ticket: str = "", appmsg_token: str = "",
                 cookie: str = "", delay_range: Optional[tuple] = None):
        self.biz = biz
        self.uin = uin
        self.key = key
        self.pass_ticket = pass_ticket
        self.appmsg_token = appmsg_token
        self.cookie = cookie
        self.delay_range = delay_range or self.DEFAULT_DELAY
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36 "
                "MicroMessenger/7.0.20.1781(0x6700143B) "
                "NetType/WIFI MiniProgramEnv/Windows WindowsWechat"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": f"https://mp.weixin.qq.com/mp/profile_ext?action=home"
                       f"&__biz={self.biz}&scene=124",
        })
        if self.cookie:
            self.session.headers["Cookie"] = self.cookie
        self._cutoff = None

    def fetch_articles(self, days: int = None, from_date: str = None,
                        to_date: str = None, callback: Optional[Callable] = None) -> List[dict]:
        if days is not None:
            self._cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).timestamp()
            self._end_ts = None
        elif from_date is not None:
            self._cutoff = datetime.fromisoformat(from_date).replace(
                tzinfo=timezone.utc).timestamp()
            self._end_ts = datetime.fromisoformat(to_date).replace(
                tzinfo=timezone.utc).timestamp() if to_date else None
        else:
            self._cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).timestamp()
            self._end_ts = None
        all_articles = []
        offset = 0

        while offset < self.MAX_PAGES * self.PAGE_SIZE:
            page = self._fetch_page_with_retry(offset)
            if page is None:
                break

            articles, should_stop = self._filter_page(page)
            all_articles.extend(articles)

            if callback:
                callback(len(all_articles), offset + len(page))

            if should_stop:
                break

            offset += self.PAGE_SIZE
            self._delay()

        return all_articles

    def _fetch_page_with_retry(self, offset: int) -> Optional[List[dict]]:
        for attempt in range(self.MAX_RETRIES):
            try:
                url = self._build_url(offset)
                resp = self.session.get(url, timeout=30)
                data = resp.json()

                ret = data.get("base_resp", {}).get("ret", 0)
                if ret == 0:
                    return self._parse_response(data)

                if self._is_key_expired(data):
                    raise KeyExpiredError(
                        f"WeChat API returned ret={ret}. "
                        "Please re-run 'start-proxy', open the target account in WeChat, "
                        "then retry fetch."
                    )

                if self._is_rate_limited(data):
                    wait = self.RATE_LIMIT_BACKOFF * (2 ** attempt)
                    wait += random.uniform(0, 5)
                    print(f"Rate limited. Waiting {wait:.0f}s...")
                    time.sleep(wait)
                    continue

                print(f"Unexpected API ret={ret}: "
                      f"{data.get('base_resp', {}).get('err_msg', '')}")
                return None

            except requests.exceptions.RequestException as e:
                print(f"Network error: {e}. Retrying in {5 * (2 ** attempt)}s...")
                time.sleep(5 * (2 ** attempt))
            except KeyExpiredError:
                raise

        print(f"Failed after {self.MAX_RETRIES} retries at offset={offset}.")
        return None

    def _build_url(self, offset: int) -> str:
        url = (
            f"{self.API_URL}?action=getmsg"
            f"&__biz={quote(self.biz, safe='')}"
            f"&f=json"
            f"&offset={offset}"
            f"&count={self.PAGE_SIZE}"
            f"&uin={quote(self.uin, safe='')}"
            f"&key={quote(self.key, safe='')}"
        )
        if self.pass_ticket:
            url += f"&pass_ticket={quote(self.pass_ticket, safe='')}"
        if self.appmsg_token:
            url += f"&appmsg_token={quote(self.appmsg_token, safe='')}"
        return url

    def _parse_response(self, data: dict) -> List[dict]:
        raw = data.get("general_msg_list")
        if not raw:
            return []

        try:
            msg_list = json.loads(raw)
        except json.JSONDecodeError:
            return []

        articles = []
        items = msg_list.get("list", [])
        for item in items:
            comm = item.get("comm_msg_info", {})
            if comm.get("type") != 49:
                continue

            create_time = comm.get("datetime")
            ext = item.get("app_msg_ext_info", {})

            if ext:
                # Main article
                url = self._normalize_url(ext.get("content_url", ""))
                articles.append({
                    "title": ext.get("title", ""),
                    "url": url,
                    "create_time": create_time,
                })
                # Secondary articles (multi-article push)
                for sub in ext.get("multi_app_msg_item_list", []):
                    articles.append({
                        "title": sub.get("title", ""),
                        "url": self._normalize_url(sub.get("content_url", "")),
                        "create_time": create_time,
                    })

        return articles

    def _filter_page(self, articles: List[dict]) -> Tuple[List[dict], bool]:
        filtered = []
        oldest_ts = None

        for a in articles:
            ts = a.get("create_time")
            if ts is None:
                continue
            oldest_ts = min(oldest_ts, ts) if oldest_ts is not None else ts
            if ts < self._cutoff:
                continue
            if self._end_ts is not None and ts > self._end_ts:
                continue
            filtered.append(a)

        stop = oldest_ts is not None and oldest_ts < self._cutoff
        return filtered, stop

    def _is_key_expired(self, data: dict) -> bool:
        ret = data.get("base_resp", {}).get("ret", 0)
        return ret in self.KEY_EXPIRED_CODES

    def _is_rate_limited(self, data: dict) -> bool:
        ret = data.get("base_resp", {}).get("ret", 0)
        err_msg = data.get("base_resp", {}).get("err_msg", "")
        return ret != 0 and any(kw in err_msg for kw in ("freq", "频繁", "limit"))

    def _delay(self):
        seconds = random.uniform(*self.delay_range)
        time.sleep(seconds)

    @staticmethod
    def _normalize_url(url: str) -> str:
        if not url:
            return ""
        url = url.replace("&amp;", "&")
        if url.startswith("//"):
            url = f"https:{url}"
        elif url.startswith("/"):
            url = f"https://mp.weixin.qq.com{url}"
        return url
