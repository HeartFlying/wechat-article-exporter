"""工作流编排：抓取 → 去重 → 下载。"""

import os
import sys
import time
from typing import List, Optional

from wechat_fetcher.storage import ParamStore
from wechat_fetcher.fetcher import WeChatArticleFetcher, KeyExpiredError
from wechat_fetcher.downloader import ArticleDownloader
from wechat_fetcher.dedup import DedupIndex


class WorkflowEngine:
    WAIT_INTERVAL = 3  # --wait-proxy 轮询间隔（秒）
    WAIT_TIMEOUT = 300  # --wait-proxy 最长等待（秒）

    def __init__(self, root_dir: str = None):
        if root_dir is None:
            root_dir = os.path.join(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))), "data")
        self._root = root_dir
        self._store = ParamStore(root_dir=root_dir)
        self._dedup = DedupIndex(root_dir=root_dir)

    def run(self, biz: str, days: int = None, from_date: str = None,
            to_date: str = None, output_dir: str = None, wait_proxy: bool = False,
            cookie: str = None) -> dict:
        return self.run_all([biz], days=days, from_date=from_date, to_date=to_date,
                            output_dir=output_dir, wait_proxy=wait_proxy, cookie=cookie)

    def run_all(self, biz_list: List[str], days: int = None, from_date: str = None,
                to_date: str = None, output_dir: str = None, wait_proxy: bool = False,
                cookie: str = None) -> dict:
        results = {"success": [], "failed": [], "skipped": [], "errors": []}

        for biz in biz_list:
            params = self._resolve_params(biz, wait_proxy)
            if params is None:
                results["errors"].append({
                    "biz": biz,
                    "reason": "参数未就绪" if wait_proxy else "无已存储参数",
                })
                continue

            try:
                self._process_biz(biz, params, days, from_date, to_date,
                                  output_dir, cookie, results)
            except KeyExpiredError:
                results["errors"].append({
                    "biz": biz,
                    "reason": "Key 已过期，请运行 start-proxy 刷新参数后重试",
                })

        return results

    def _resolve_params(self, biz: str, wait_proxy: bool) -> Optional[dict]:
        params = self._store.load(biz)
        if params is not None:
            return params

        if not wait_proxy:
            return None

        print(f"等待 {biz} 的参数就绪...")
        print("  请在微信中打开目标公众号并浏览历史文章")
        elapsed = 0
        while elapsed < self.WAIT_TIMEOUT:
            time.sleep(self.WAIT_INTERVAL)
            elapsed += self.WAIT_INTERVAL
            params = self._store.load(biz)
            if params is not None:
                print(f"  参数就绪（等待 {elapsed}s）")
                return params
            print(f"  等待中...（{elapsed}s/{self.WAIT_TIMEOUT}s）")

        return None

    def _process_biz(self, biz: str, params: dict, days: int, from_date: str,
                     to_date: str, output_dir: str, cookie: str, results: dict) -> None:
        label = f"[{biz[:16]}...]"
        print(f"\n{label} 开始抓取...")

        fetcher = WeChatArticleFetcher(
            biz=params["__biz"],
            uin=params["uin"],
            key=params["key"],
            pass_ticket=params.get("pass_ticket", ""),
            appmsg_token=params.get("appmsg_token", ""),
            cookie=cookie or params.get("cookie", ""),
        )

        articles = fetcher.fetch_articles(
            days=days, from_date=from_date, to_date=to_date)

        # 去重
        new_articles = []
        skipped_count = 0
        for a in articles:
            title = a.get("title", "")
            url = a.get("url", "")
            if self._dedup.is_duplicate(biz, title, url):
                skipped_count += 1
            else:
                new_articles.append(a)

        if skipped_count:
            print(f"{label} 去重跳过 {skipped_count} 篇")

        if not new_articles:
            print(f"{label} 无新文章")
            return

        print(f"{label} {len(articles)} 篇 → {len(new_articles)} 篇新文章，开始下载...")

        downloader = ArticleDownloader(
            output_dir=output_dir or os.path.join(self._root, "articles"),
            cookie=cookie or params.get("cookie", ""),
        )

        for i, a in enumerate(new_articles, 1):
            title = a.get("title", "无标题")
            url = a.get("url", "")
            date = a.get("date", "")

            safe_title = downloader.sanitize_filename(title)
            folder_name = f"{date}_{safe_title}" if date else safe_title
            article_dir = downloader.output_dir / folder_name

            if article_dir.exists() and (article_dir / "content.md").exists():
                results["skipped"].append({"biz": biz, "title": title, "url": url})
                self._dedup.mark_seen(biz, title, url)
                continue

            print(f"  [{i}/{len(new_articles)}] 下载: {title}")
            html = downloader.download_article(url)
            if html is None:
                results["failed"].append({"biz": biz, "title": title, "url": url})
                continue

            content = downloader.extract_article_content(html)
            filepath = downloader.save_article(title, content, date)

            if filepath:
                results["success"].append({"biz": biz, "title": title, "url": url, "file": filepath})
                self._dedup.mark_seen(biz, title, url)
            else:
                results["failed"].append({"biz": biz, "title": title, "url": url})

        print(f"{label} 完成：成功 {len([r for r in results['success'] if r['biz'] == biz])}，"
              f"跳过 {len([r for r in results['skipped'] if r['biz'] == biz])}，"
              f"失败 {len([r for r in results['failed'] if r['biz'] == biz])}")
