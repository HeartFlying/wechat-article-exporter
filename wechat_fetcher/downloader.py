"""Download WeChat articles and convert to Markdown."""

import json
import os
import re
import time
import random
from pathlib import Path
from typing import List, Optional

import requests
from bs4 import BeautifulSoup
from markdownify import markdownify


class ArticleDownloader:
    """Download WeChat articles and save as Markdown."""

    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36 "
        "MicroMessenger/7.0.20.1781(0x6700143B) "
        "NetType/WIFI MiniProgramEnv/Windows WindowsWechat"
    )

    MAX_RETRIES = 3
    RETRY_DELAY = 5
    DOWNLOAD_DELAY = (2.0, 4.0)

    def __init__(self, output_dir: str = None, cookie: str = None):
        if output_dir is None:
            output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "articles")
        self.output_dir = Path(output_dir)
        self.cookie = cookie
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
        if cookie:
            self.session.headers["Cookie"] = cookie

    def load_articles(self, articles_file: str) -> List[dict]:
        """Load articles list from JSON file."""
        with open(articles_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data

    def sanitize_filename(self, name: str, max_length: int = 100) -> str:
        """Remove invalid characters from filename."""
        invalid_chars = r'[<>:"/\\|?*]'
        name = re.sub(invalid_chars, "_", name)
        name = name.strip().strip(".")
        if len(name) > max_length:
            name = name[:max_length]
        return name

    def download_article(self, url: str) -> Optional[str]:
        """Download article HTML and return content."""
        for attempt in range(self.MAX_RETRIES):
            try:
                resp = self.session.get(url, timeout=30)
                resp.raise_for_status()
                resp.encoding = "utf-8"
                return resp.text
            except requests.exceptions.RequestException as e:
                if attempt < self.MAX_RETRIES - 1:
                    wait = self.RETRY_DELAY * (2 ** attempt) + random.uniform(0, 2)
                    print(f"  Download failed: {e}. Retrying in {wait:.1f}s...")
                    time.sleep(wait)
                else:
                    print(f"  Download failed after {self.MAX_RETRIES} retries: {e}")
                    return None

    def extract_article_content(self, html: str) -> str:
        """Extract main article content and convert to Markdown."""
        soup = BeautifulSoup(html, "html.parser")

        title_tag = soup.find("h1", id="activity-name")
        if title_tag:
            title = title_tag.get_text(strip=True)
        else:
            title_tag = soup.find("title")
            title = title_tag.get_text(strip=True) if title_tag else "无标题"

        content = soup.find("div", id="js_content")
        if content is None:
            content = soup.find("div", class_="rich_media_content")

        if content is None:
            return f"# {title}\n\n[!] 无法提取文章内容\n"

        for tag in content.find_all(["script", "style", "iframe"]):
            tag.decompose()

        for img in content.find_all("img"):
            src = img.get("data-src") or img.get("src")
            if src:
                img.replace_with(f"![{img.get('alt', 'image')}]({src})")

        for a_tag in content.find_all("a"):
            href = a_tag.get("href", "")
            if href:
                a_tag.string = f"{a_tag.get_text(strip=True)} ({href})"

        for br in content.find_all("br"):
            br.replace_with("\n")

        md = markdownify(str(content), heading_style="ATX", strip=["script", "style"])
        md = md.strip()

        md = re.sub(r"\n{3,}", "\n\n", md)

        return f"# {title}\n\n{md}\n"

    def save_article(self, title: str, content: str, date: str = None) -> Optional[str]:
        """Save article as Markdown file in title-named folder."""
        safe_title = self.sanitize_filename(title)
        if not safe_title:
            safe_title = f"article_{int(time.time())}"

        if date:
            folder_name = f"{date}_{safe_title}"
        else:
            folder_name = safe_title

        article_dir = self.output_dir / folder_name
        article_dir.mkdir(parents=True, exist_ok=True)

        filename = "content.md"
        filepath = article_dir / filename

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

        return str(filepath)

    def download_all(self, articles: List[dict], start: int = 0, end: int = None,
                      dedup=None) -> dict:
        """Download all articles and save as Markdown."""
        if end is None:
            end = len(articles)

        articles_to_download = articles[start:end]
        total = len(articles_to_download)
        
        results = {
            "success": [],
            "failed": [],
            "skipped": []
        }

        print(f"\n开始下载 {total} 篇文章...")
        print(f"输出目录: {self.output_dir}\n")

        for i, article in enumerate(articles_to_download, 1):
            title = article.get("title", "无标题")
            url = article.get("url", "")
            date = article.get("date", "")

            safe_title = self.sanitize_filename(title)
            folder_name = f"{date}_{safe_title}" if date else safe_title
            article_dir = self.output_dir / folder_name

            if article_dir.exists() and (article_dir / "content.md").exists():
                print(f"[{i}/{total}] 跳过 (已存在): {title}")
                results["skipped"].append({"title": title, "url": url})
                continue

            if dedup and dedup.is_duplicate(article.get("biz", ""), title, url):
                print(f"[{i}/{total}] 跳过 (去重): {title}")
                results["skipped"].append({"title": title, "url": url})
                continue

            print(f"[{i}/{total}] 下载: {title}")
            
            html = self.download_article(url)
            if html is None:
                results["failed"].append({"title": title, "url": url})
                continue

            content = self.extract_article_content(html)
            filepath = self.save_article(title, content, date)
            
            if filepath:
                print(f"  [OK] 保存至: {filepath}")
                results["success"].append({
                    "title": title,
                    "url": url,
                    "file": filepath
                })
                if dedup:
                    dedup.mark_seen(article.get("biz", ""), title, url)
            else:
                print(f"  [FAIL] 保存失败")
                results["failed"].append({"title": title, "url": url})

            if i < total:
                delay = random.uniform(*self.DOWNLOAD_DELAY)
                time.sleep(delay)

        print(f"\n下载完成!")
        print(f"  成功: {len(results['success'])}")
        print(f"  跳过: {len(results['skipped'])}")
        print(f"  失败: {len(results['failed'])}")

        return results
