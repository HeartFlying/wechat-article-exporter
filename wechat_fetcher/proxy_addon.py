"""mitmproxy addon: intercept WeChat Official Account requests and extract auth params."""

from typing import Optional

from mitmproxy import http, ctx
from urllib.parse import parse_qs, urlparse

from wechat_fetcher.storage import ParamStore

TARGET_HOST = "mp.weixin.qq.com"


class WeChatInterceptor:
    def __init__(self):
        self.store = ParamStore()
        self._seen_biz: set = set()

    def request(self, flow: http.HTTPFlow) -> None:
        host = flow.request.pretty_host
        if TARGET_HOST not in host:
            return

        params = self._extract_params(flow)
        if not params:
            return

        biz, uin, key, pass_ticket, appmsg_token = params
        cookie = self._extract_cookie(flow)

        if biz not in self._seen_biz:
            ctx.log.info(f"Captured params for __biz={biz}")
            self._seen_biz.add(biz)

        self.store.save(biz, uin, key,
                        pass_ticket=pass_ticket,
                        appmsg_token=appmsg_token,
                        cookie=cookie)

    def _extract_params(self, flow: http.HTTPFlow) -> Optional[tuple]:
        # Collect query params from all sources into a flat dict
        all_qs = {}

        # Source 1: flow.request.query fields (tuple of (k, v) pairs)
        for k, v in flow.request.query.fields:
            all_qs[k] = v

        # Source 2: parsed full URL query
        for k, v_list in parse_qs(urlparse(flow.request.url).query).items():
            if k not in all_qs:
                all_qs[k] = v_list[0] if v_list else None

        # Source 3: Referer header query params
        referer = flow.request.headers.get("referer", "")
        if referer:
            for k, v_list in parse_qs(urlparse(referer).query).items():
                if k not in all_qs:
                    all_qs[k] = v_list[0] if v_list else None

        # Source 4: Cookie header (params sometimes stored there)
        cookie = flow.request.headers.get("cookie", "")
        if cookie:
            for pair in cookie.split(";"):
                pair = pair.strip()
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    if k not in all_qs:
                        all_qs[k] = v

        biz = all_qs.get("__biz")
        uin = all_qs.get("uin")
        key = all_qs.get("key")
        pass_ticket = all_qs.get("pass_ticket", "")
        appmsg_token = all_qs.get("appmsg_token", "")

        if all([biz, uin, key]):
            return (biz, uin, key, pass_ticket, appmsg_token)

        if biz and uin and not key:
            ctx.log.debug(
                f"Partial capture: __biz={biz}, uin=***, key missing. "
                "Scroll through the account's article list to trigger the full API call."
            )

        return None

    @staticmethod
    def _extract_cookie(flow: http.HTTPFlow) -> str:
        return flow.request.headers.get("cookie", "")

    def done(self):
        accounts = self.store.list_accounts()
        if accounts:
            ctx.log.info(f"Session ended. Captured {len(accounts)} account(s):")
            for a in accounts:
                ctx.log.info(f"  __biz={a['__biz']}")


addons = [WeChatInterceptor()]
