"""mitmproxy addon: intercept WeChat Official Account requests and extract auth params."""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from mitmproxy import http, ctx
from urllib.parse import parse_qs, urlparse, unquote

from wechat_fetcher.storage import ParamStore
from wechat_fetcher.config import get_config

TARGET_HOST = "mp.weixin.qq.com"


class WeChatInterceptor:
    def __init__(self, verbose: bool = False):
        self.store = ParamStore()
        self._seen_biz: set = set()
        self._verbose = verbose

        # 初始化抓包分析日志
        config = get_config()
        self._capture_log_dir = Path(config.data_dir) / "capture_logs"
        self._capture_log_dir.mkdir(parents=True, exist_ok=True)
        self._capture_log_file = self._capture_log_dir / f"capture_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
        self._analysis_data = {
            "start_time": datetime.now().isoformat(),
            "requests": [],
            "name_candidates": {},  # biz -> list of candidates
            "final_names": {},  # biz -> final name
        }

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

    def response(self, flow: http.HTTPFlow) -> None:
        """从响应中提取公众号名称信息。"""
        host = flow.request.pretty_host
        if TARGET_HOST not in host:
            return

        # 尝试从响应中提取公众号名称
        account_name, candidates = self._extract_account_name(flow)

        # 获取当前请求的 biz
        params = self._extract_params(flow)
        biz = params[0] if params else None

        # 记录分析数据
        self._log_capture_data(flow, biz, account_name, candidates)

        if account_name and biz:
            self.store.update_account_info(biz, name=account_name)
            # 记录最终名称
            if biz not in self._analysis_data["final_names"]:
                self._analysis_data["final_names"][biz] = account_name

    def _log_capture_data(self, flow: http.HTTPFlow, biz: Optional[str],
                          final_name: Optional[str], candidates: list) -> None:
        """记录抓包分析数据到日志文件。"""
        try:
            # 构建请求/响应摘要
            capture_entry = {
                "timestamp": datetime.now().isoformat(),
                "url": flow.request.url,
                "biz": biz,
                "content_type": flow.response.headers.get("content-type", ""),
                "final_name": final_name,
                "candidates": candidates,
            }

            # 保存到 JSONL 文件
            with open(self._capture_log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(capture_entry, ensure_ascii=False) + "\n")

            # 更新内存中的候选列表
            if biz and candidates:
                if biz not in self._analysis_data["name_candidates"]:
                    self._analysis_data["name_candidates"][biz] = []
                self._analysis_data["name_candidates"][biz].extend(candidates)

        except Exception as e:
            ctx.log.debug(f"[CaptureLog] 记录失败: {e}")

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

    def _extract_account_name(self, flow: http.HTTPFlow) -> tuple[Optional[str], list]:
        """从响应中提取公众号名称。

        微信 API 返回的数据中通常包含公众号信息：
        1. profile_ext API 返回的 JSON 中有 nick_name 字段
        2. 页面 HTML 中可能包含公众号名称

        Returns:
            (最终名称, 候选列表)
        """
        import re

        content_type = flow.response.headers.get("content-type", "")
        url = flow.request.url
        candidates = []  # 收集所有候选名称

        # 根据 verbose 模式选择日志级别
        log_func = ctx.log.info if self._verbose else ctx.log.debug

        log_func(f"[NameDebug] 开始解析名称 - URL: {url[:80]}...")

        # 尝试从 JSON 响应中提取
        if "application/json" in content_type or "text/javascript" in content_type:
            try:
                text = flow.response.text
                # 微信 API 返回的是 JSONP 格式，需要提取 JSON 部分
                if text.startswith("callback(") or text.startswith("__jp"):
                    # 提取 JSONP 中的 JSON 部分
                    start = text.find("(") + 1
                    end = text.rfind(")")
                    if start > 0 and end > start:
                        text = text[start:end]

                data = json.loads(text)

                # 优先从根级别获取（profile_ext API 返回的 nick_name 最可靠）
                nickname = data.get("nick_name") or data.get("nickname")
                if nickname:
                    log_func(f"[NameDebug] JSON根级别 nick_name: {nickname}, 有效: {self._is_valid_nickname(nickname)}")
                    candidates.append({"source": "json_root_nick_name", "value": nickname, "valid": self._is_valid_nickname(nickname)})
                    if self._is_valid_nickname(nickname):
                        return nickname, candidates

                # 从 msglist 中提取（备用方案）
                msg_list = data.get("general_msg_list")
                if msg_list:
                    try:
                        msg_data = json.loads(msg_list)
                        items = msg_data.get("list", [])
                        for item in items:
                            ext = item.get("app_msg_ext_info", {})
                            nickname = ext.get("nick_name")
                            if nickname:
                                log_func(f"[NameDebug] msg_list nick_name: {nickname}, 有效: {self._is_valid_nickname(nickname)}")
                                candidates.append({"source": "msg_list_nick_name", "value": nickname, "valid": self._is_valid_nickname(nickname)})
                                if self._is_valid_nickname(nickname):
                                    return nickname, candidates
                    except json.JSONDecodeError:
                        pass

            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                log_func(f"[NameDebug] JSON解析失败: {e}")

        # 尝试从 HTML 响应中提取（公众号主页）
        if "text/html" in content_type:
            try:
                text = flow.response.text

                # 模式1: 公众号主页的 profile_nickname
                match = re.search(r'profile_nickname[^>]*>([^<]+)', text)
                if match:
                    nickname = match.group(1).strip()
                    log_func(f"[NameDebug] HTML profile_nickname: {nickname}, 有效: {self._is_valid_nickname(nickname)}")
                    candidates.append({"source": "html_profile_nickname", "value": nickname, "valid": self._is_valid_nickname(nickname)})
                    if self._is_valid_nickname(nickname):
                        return nickname, candidates

                # 模式2: rich_media_meta_nickname（文章页）
                match = re.search(r'rich_media_meta_nickname[^>]*>([^<]+)', text)
                if match:
                    nickname = match.group(1).strip()
                    log_func(f"[NameDebug] HTML rich_media_meta_nickname: {nickname}, 有效: {self._is_valid_nickname(nickname)}")
                    candidates.append({"source": "html_rich_media_meta", "value": nickname, "valid": self._is_valid_nickname(nickname)})
                    if self._is_valid_nickname(nickname):
                        return nickname, candidates

                # 模式3: nickname 变量（JSON 格式）
                match = re.search(r'"nickname"\s*:\s*"([^"]+)"', text)
                if match:
                    nickname = match.group(1)
                    log_func(f"[NameDebug] HTML json_nickname: {nickname}, 有效: {self._is_valid_nickname(nickname)}")
                    candidates.append({"source": "html_json_nickname", "value": nickname, "valid": self._is_valid_nickname(nickname)})
                    if self._is_valid_nickname(nickname):
                        return unquote(nickname), candidates

                # 模式4: nickname 变量（JS 格式）
                match = re.search(r'nickname\s*=\s*["\']([^"\']+)["\']', text)
                if match:
                    nickname = match.group(1)
                    log_func(f"[NameDebug] HTML js_nickname: {nickname}, 有效: {self._is_valid_nickname(nickname)}")
                    candidates.append({"source": "html_js_nickname", "value": nickname, "valid": self._is_valid_nickname(nickname)})
                    if self._is_valid_nickname(nickname):
                        return unquote(nickname), candidates

                # 模式5: 页面标题（最后备选）
                match = re.search(r'<title>([^<]+)</title>', text)
                if match:
                    title = match.group(1).strip()
                    log_func(f"[NameDebug] HTML title: {title}")
                    is_valid = title and "微信" not in title and "WeChat" not in title and len(title) > 1
                    candidates.append({"source": "html_title", "value": title, "valid": is_valid})
                    # 过滤掉微信相关的通用标题
                    if is_valid:
                        return title, candidates

            except Exception as e:
                log_func(f"[NameDebug] HTML解析失败: {e}")

        # 如果没有找到有效名称，打印所有候选
        if candidates:
            log_func(f"[NameDebug] 所有候选名称: {candidates}")
        else:
            log_func(f"[NameDebug] 未找到任何名称候选")

        return None, candidates

    @staticmethod
    def _is_valid_nickname(nickname: str) -> bool:
        """验证昵称是否有效。

        过滤掉：
        - 空字符串
        - 纯数字（可能是 ID）
        - 过短的字符串（可能是乱码）
        - 明显的非名称内容
        """
        if not nickname:
            return False

        nickname = nickname.strip()

        # 长度检查
        if len(nickname) < 2:
            return False

        # 纯数字检查（可能是 user_id 而非名称）
        if nickname.isdigit():
            return False

        # 检查是否包含明显的非名称字符
        invalid_patterns = [
            r'^\d+$',  # 纯数字
            r'^[a-zA-Z0-9]{20,}$',  # 长串字母数字（可能是编码）
            r'[<>"\']',  # HTML 标签字符
        ]

        for pattern in invalid_patterns:
            if re.search(pattern, nickname):
                return False

        return True

    def done(self):
        accounts = self.store.list_accounts()
        if accounts:
            ctx.log.info(f"Session ended. Captured {len(accounts)} account(s):")
            for a in accounts:
                name = a.get("name", "")
                name_str = f" ({name})" if name else ""
                ctx.log.info(f"  __biz={a['__biz']}{name_str}")

        # 保存分析汇总报告
        self._save_analysis_report()

    def _save_analysis_report(self) -> None:
        """保存抓包分析汇总报告。"""
        try:
            self._analysis_data["end_time"] = datetime.now().isoformat()
            self._analysis_data["capture_log_file"] = str(self._capture_log_file)

            # 去重候选名称
            for biz in self._analysis_data["name_candidates"]:
                seen = set()
                unique_candidates = []
                for c in self._analysis_data["name_candidates"][biz]:
                    key = (c["source"], c["value"])
                    if key not in seen:
                        seen.add(key)
                        unique_candidates.append(c)
                self._analysis_data["name_candidates"][biz] = unique_candidates

            # 保存汇总报告
            report_file = self._capture_log_dir / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(report_file, "w", encoding="utf-8") as f:
                json.dump(self._analysis_data, f, ensure_ascii=False, indent=2)

            ctx.log.info(f"[CaptureLog] 分析报告已保存: {report_file}")
            ctx.log.info(f"[CaptureLog] 详细日志: {self._capture_log_file}")

        except Exception as e:
            ctx.log.debug(f"[CaptureLog] 保存报告失败: {e}")


addons = [WeChatInterceptor()]
