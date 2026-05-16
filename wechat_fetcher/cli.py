import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import click

from wechat_fetcher.storage import ParamStore
from wechat_fetcher.fetcher import WeChatArticleFetcher, KeyExpiredError
from wechat_fetcher.downloader import ArticleDownloader
from wechat_fetcher.dedup import DedupIndex
from wechat_fetcher.workflow import WorkflowEngine


def _find_mitmdump() -> str:
    scripts_dir = os.path.join(os.path.dirname(sys.executable), "Scripts") if os.name == "nt" \
        else os.path.join(os.path.dirname(sys.executable), "..", "bin")
    exe = "mitmdump.exe" if os.name == "nt" else "mitmdump"
    path = os.path.join(scripts_dir, exe)
    if os.path.isfile(path):
        return path
    return "mitmdump"


@click.group()
def main():
    """WeChat Official Account article URL fetcher."""
    pass


@main.command()
@click.option("--port", default=8080, help="Proxy port (default: 8080)")
@click.option("--listen-host", default="0.0.0.0", help="Listen address (default: 0.0.0.0)")
@click.option("--show-ip", is_flag=True, help="Show local IP for phone proxy config")
def start_proxy(port, listen_host, show_ip):
    """Start MITM proxy to intercept WeChat requests and extract auth params."""
    print("WeChat Article Fetcher Proxy")
    print("=" * 60)
    print(f"Proxy listening on {listen_host}:{port}")
    print()

    if show_ip:
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            print(f"Your local IP: {local_ip}")
        except Exception:
            print("Could not determine local IP.")
        print()

    print("Instructions:")
    if show_ip:
        print(" [Phone Mode]")
        print("1. Configure your phone's Wi-Fi proxy:")
        print(f"   Server: <your computer IP>  Port: {port}")
        print()
        print("2. Install the mitmproxy CA certificate:")
        print("   Open http://mitm.it on your phone (proxy must be active)")
        print("   iOS: Settings > General > VPN & Device Management")
        print("   Android: Settings > Security > Install from storage")
        print()
        print("3. Open WeChat, find the target Official Account.")
        print("4. Tap 'View all articles' and scroll down to load more.")
    else:
        print(" [Desktop Mode]")
        print("1. Set Windows system proxy:")
        print(f"   Win+I > Network & Internet > Proxy > Manual")
        print(f"   Address: 127.0.0.1  Port: {port}")
        print()
        print("2. Install the mitmproxy CA certificate:")
        print("   Open http://mitm.it in your browser (proxy must be active)")
        print("   Download the Windows certificate and install to:")
        print("   'Trusted Root Certification Authorities'")
        print()
        print("3. Restart WeChat Desktop (fully quit and reopen).")
        print("4. Open the target Official Account, click 'All Articles',")
        print("   and scroll down to load more.")
    print()
    print("5. Watch this window for 'Captured params' log messages.")
    print()
    print("Press Ctrl+C to stop.")
    print("=" * 60)
    print()

    cmd = [
        _find_mitmdump(),
        "-s", os.path.join(os.path.dirname(os.path.abspath(__file__)), "proxy_addon.py"),
        "-p", str(port),
        "--listen-host", listen_host,
    ]
    try:
        subprocess.run(cmd, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    except KeyboardInterrupt:
        print("\nProxy stopped.")
    except FileNotFoundError:
        print("mitmdump not found. Please run: uv sync")
        sys.exit(1)


@main.command()
@click.option("--biz", required=True, help="The __biz value of the target account")
@click.option("--days", type=int, help="Number of days to fetch")
@click.option("--from", "from_date", help="Start date (YYYY-MM-DD)")
@click.option("--to", "to_date", help="End date (YYYY-MM-DD)")
@click.option("--output", type=click.Path(writable=True), help="Write JSON to file instead of stdout")
def fetch(biz, days, from_date, to_date, output):
    """Fetch article URLs from a WeChat Official Account."""
    store = ParamStore()
    params = store.load(biz)

    if params is None:
        click.echo(f"No stored params for __biz={biz}", err=True)
        accounts = store.list_accounts()
        if accounts:
            if len(accounts) == 1:
                click.echo(f"Did you mean: {accounts[0]['__biz']} ?", err=True)
            click.echo("\nStored accounts:", err=True)
            for a in accounts:
                click.echo(f"  {a['__biz']}  ({a.get('extracted_at', '?')})", err=True)
        else:
            click.echo("Run 'start-proxy' first, then open the target account in WeChat.", err=True)
        sys.exit(1)

    key_age = None
    if params.get("extracted_at"):
        try:
            extracted = datetime.fromisoformat(params["extracted_at"])
            key_age = (datetime.now(timezone.utc) - extracted).total_seconds()
        except (ValueError, TypeError):
            pass

    click.echo(f"Params for {biz}")
    if key_age is not None:
        age_str = f"{key_age:.0f}s ago" if key_age < 3600 else f"{key_age / 3600:.1f}h ago"
        freshness = "fresh" if key_age < 3600 else "[!] may be expired"
        click.echo(f"  Key extracted: {params['extracted_at']} ({age_str}) ({freshness})")
    if not params.get("pass_ticket") and not params.get("cookie"):
        click.echo("  [!] Missing pass_ticket/cookie in stored params — re-capture with updated proxy")
    click.echo()

    date_label = f"last {days} days" if days else f"{from_date} to {to_date}"
    click.echo(f"Fetching articles from {date_label}...")
    fetcher = WeChatArticleFetcher(
        biz=params["__biz"],
        uin=params["uin"],
        key=params["key"],
        pass_ticket=params.get("pass_ticket", ""),
        appmsg_token=params.get("appmsg_token", ""),
        cookie=params.get("cookie", ""),
    )

    try:
        articles = fetcher.fetch_articles(
            days=days, from_date=from_date, to_date=to_date)
    except KeyExpiredError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    click.echo(f"\nFound {len(articles)} articles.\n")

    result = []
    for article in articles:
        ts = article.get("create_time")
        date_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d") if ts else "?"
        result.append({
            "title": article["title"],
            "url": article["url"],
            "date": date_str,
        })

    if output:
        import json
        out_path = Path(output)
        if out_path.is_dir():
            out_path = out_path / f"articles_{biz}.json"
            click.echo(f"Output is a directory, writing to {out_path}")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        click.echo(f"Written to {out_path}")
    else:
        for i, r in enumerate(result, 1):
            click.echo(f"{i}. {r['title']}")
            click.echo(f"   {r['url']}")
            click.echo(f"   {r['date']}")
            click.echo()


@main.command()
@click.option("--verbose", is_flag=True, help="Show full key/uin values")
def status(verbose):
    """Show stored WeChat account parameters and dedup index."""
    store = ParamStore()
    accounts = store.list_accounts()

    if not accounts:
        click.echo("No stored accounts.")
        click.echo("Run 'start-proxy' and open a WeChat Official Account.")
    else:
        click.echo(f"Stored accounts ({store._params_dir}):\n")
        for a in accounts:
            biz = a["__biz"]
            extracted = a.get("extracted_at", "?")
            try:
                et = datetime.fromisoformat(extracted)
                age = (datetime.now(timezone.utc) - et).total_seconds()
                age_str = f"{age:.0f}s ago" if age < 3600 else f"{age / 3600:.1f}h ago"
                freshness = "fresh" if age < 3600 else "[!] may be expired"
            except (ValueError, TypeError):
                age_str = "?"
                freshness = "?"

            click.echo(f"  {biz}")
            click.echo(f"    Extracted: {extracted} ({age_str}) {freshness}")
            if verbose:
                full = store.load(biz)
                if full:
                    click.echo(f"    uin: {full.get('uin', '?')}")
                    click.echo(f"    key: {full.get('key', '?')}")
            click.echo()

    dedup = DedupIndex()
    ds = dedup.stats()
    click.echo(f"去重索引 ({dedup._index_path}):")
    click.echo(f"  文章标题: {ds['total_titles']}  文章URL: {ds['total_urls']}  账号数: {ds['accounts']}")


@main.command()
@click.option("--input", "input_file", required=True, help="Path to articles JSON file")
@click.option("--output-dir", help="Output directory (default: data/articles)")
@click.option("--cookie", help="Cookie for WeChat authentication")
@click.option("--start", default=0, help="Start index (default: 0)")
@click.option("--end", type=int, help="End index (default: all)")
def download(input_file, output_dir, cookie, start, end):
    """Download articles and convert to Markdown."""
    downloader = ArticleDownloader(output_dir=output_dir, cookie=cookie)

    if not os.path.exists(input_file):
        click.echo(f"Error: File not found: {input_file}", err=True)
        sys.exit(1)

    articles = downloader.load_articles(input_file)
    click.echo(f"Loaded {len(articles)} articles from {input_file}")

    if start >= len(articles):
        click.echo(f"Error: Start index {start} exceeds article count", err=True)
        sys.exit(1)

    dedup = DedupIndex()
    results = downloader.download_all(articles, start=start, end=end, dedup=dedup)

    if results["failed"]:
        click.echo(f"\nFailed articles:", err=True)
        for item in results["failed"]:
            click.echo(f"  - {item['title']}", err=True)
            click.echo(f"    {item['url']}", err=True)


@main.command()
@click.option("--biz", multiple=True, help="Target account __biz (repeatable, e.g. --biz A --biz B)")
@click.option("--all", "all_accounts", is_flag=True, help="Process all stored accounts")
@click.option("--days", type=int, help="Fetch articles from last N days")
@click.option("--from", "from_date", help="Start date (YYYY-MM-DD)")
@click.option("--to", "to_date", help="End date (YYYY-MM-DD)")
@click.option("--output-dir", help="Output directory (default: data/articles)")
@click.option("--cookie", help="Cookie for WeChat authentication")
@click.option("--wait-proxy", is_flag=True, help="Wait for proxy to capture params before starting")
def run(biz, all_accounts, days, from_date, to_date, output_dir, cookie, wait_proxy):
    """One-shot workflow: fetch → dedup → download (multi-account)."""
    if not biz and not all_accounts:
        click.echo("请指定 --biz 或 --all", err=True)
        sys.exit(1)

    store = ParamStore()
    if all_accounts:
        biz_list = [a["__biz"] for a in store.list_accounts()]
        if not biz_list:
            click.echo("无已存储账号。请先运行 start-proxy 并打开目标公众号。", err=True)
            sys.exit(1)
        click.echo(f"处理 {len(biz_list)} 个账号: {', '.join(biz_list)}")
    else:
        biz_list = list(biz)

    engine = WorkflowEngine()
    results = engine.run_all(
        biz_list=biz_list,
        days=days,
        from_date=from_date,
        to_date=to_date,
        output_dir=output_dir,
        wait_proxy=wait_proxy,
        cookie=cookie,
    )

    # 摘要
    total_success = len(results["success"])
    total_skipped = len(results["skipped"])
    total_failed = len(results["failed"])
    total_errors = len(results["errors"])

    print(f"\n{'=' * 50}")
    print(f"工作流完成")
    print(f"  成功: {total_success}  跳过: {total_skipped}  失败: {total_failed}")
    if total_errors:
        print(f"  参数错误: {total_errors}")
        for e in results["errors"]:
            print(f"    - {e['biz']}: {e['reason']}")

    if total_errors == len(biz_list):
        sys.exit(1)
    elif total_errors > 0 or total_failed > 0:
        sys.exit(2)
