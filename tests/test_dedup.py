"""DedupIndex 单元测试。"""

import json
import tempfile
import os

from wechat_fetcher.dedup import DedupIndex


def test_is_duplicate_title():
    idx = DedupIndex(root_dir=tempfile.mkdtemp())
    biz = "test_biz_001"
    assert not idx.is_duplicate(biz, "文章A", "https://example.com/a")
    idx.mark_seen(biz, "文章A", "https://example.com/a")
    assert idx.is_duplicate(biz, "文章A", "https://example.com/b")
    assert idx.is_duplicate(biz, "其他标题", "https://example.com/a")


def test_url_match_only():
    idx = DedupIndex(root_dir=tempfile.mkdtemp())
    biz = "test_biz_001"
    idx.mark_seen(biz, "文章A", "https://example.com/a")
    assert idx.is_duplicate(biz, "文章B", "https://example.com/a")


def test_title_match_only():
    idx = DedupIndex(root_dir=tempfile.mkdtemp())
    biz = "test_biz_001"
    idx.mark_seen(biz, "文章A", "https://example.com/a")
    assert idx.is_duplicate(biz, "文章A", "https://example.com/c")


def test_cross_biz_isolation():
    idx = DedupIndex(root_dir=tempfile.mkdtemp())
    biz_a = "biz_aaa"
    biz_b = "biz_bbb"
    idx.mark_seen(biz_a, "文章共享标题", "https://example.com/aaa")
    assert not idx.is_duplicate(biz_b, "文章共享标题", "https://example.com/bbb")


def test_stats():
    idx = DedupIndex(root_dir=tempfile.mkdtemp())
    idx.mark_seen("biz_a", "标题1", "https://a.com/1")
    idx.mark_seen("biz_a", "标题2", "https://a.com/2")
    idx.mark_seen("biz_b", "标题3", "https://b.com/1")
    assert idx.stats()["total_titles"] == 3
    assert idx.stats()["total_urls"] == 3
    assert idx.stats()["accounts"] == 2
    assert idx.stats(biz="biz_a")["titles"] == 2


def test_persistence():
    d = tempfile.mkdtemp()
    idx1 = DedupIndex(root_dir=d)
    idx1.mark_seen("biz_x", "持久化测试", "https://x.com/p")
    idx2 = DedupIndex(root_dir=d)
    assert idx2.is_duplicate("biz_x", "持久化测试", "https://x.com/p")


def test_empty_title_and_url_not_duplicate():
    idx = DedupIndex(root_dir=tempfile.mkdtemp())
    assert not idx.is_duplicate("biz_x", "", "")
    idx.mark_seen("biz_x", "", "")
    # 空标题和空 URL 不登记，避免误判
    assert not idx.is_duplicate("biz_x", "", "")
