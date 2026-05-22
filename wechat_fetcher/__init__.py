"""WeChat Fetcher - 微信公众号文章抓取工具。"""

__version__ = "0.2.0"
__author__ = "HeartFlying"
__description__ = "微信公众号文章URL抓取工具"

from wechat_fetcher.fetcher import WeChatArticleFetcher, KeyExpiredError
from wechat_fetcher.downloader import ArticleDownloader
from wechat_fetcher.storage import ParamStore
from wechat_fetcher.dedup import DedupIndex
from wechat_fetcher.workflow import WorkflowEngine

__all__ = [
    "WeChatArticleFetcher",
    "KeyExpiredError",
    "ArticleDownloader",
    "ParamStore",
    "DedupIndex",
    "WorkflowEngine",
]
