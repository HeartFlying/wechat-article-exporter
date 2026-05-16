import os
import subprocess
import sys
from datetime import datetime, timezone

import click

from wechat_fetcher.storage import ParamStore
from wechat_fetcher.fetcher import WeChatArticleFetcher, KeyExpiredError


def _find_mitmdump() -> str:
    """Locate the mitmdump executable within the current venv."""
    scripts_dir = os.path.join(os.path.dirname(sys.executable), "Scripts") if os.name == "nt" \
        else os.path.join(os.path.dirname(sys.executable), "..", "bin")
    exe = "mitmdump.exe" if os.name == "nt" else "mitmdump"
    path = os.path.join(scripts_dir, exe)
    if os.path.isfile(path):
        return path
    # Fallback: rely on PATH
    return "mitmdump"


@click.group()
def main():
    """WeChat Official Account article URL fetcher."""
    pass


@main.command()
@click.option("--port", default=8080, help="Proxy port (default: 8080)")
@click.option("--listen-host", default="0.0.0.0", help="Listen address (default: 0.0.0.0)")
@click.option("--show-ip", is_flag=True, help="Show local IP for phone proxy config")
def start_proxy(port, listen_host, show_ip):  # noqa: F811
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
        # Phone mode
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
        # Desktop mode (default)
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
        "-s", "proxy_addon.py",
        "-p", str(port),
        "--listen-host", listen_host,
    ]
    try:
        subprocess.run(cmd, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    except KeyboardInterrupt:
        print("\nProxy stopped.")
    except FileNotFoundError:
        print(
            "mitmdump not found. Please run: uv sync"
        )
        sys.exit(1)


@main.command()
@click.option("--biz", required=True, help="The __biz value of the target account")
@click.option("--days", default=30, help="Number of days to fetch (default: 30)")
@click.option("--output", type=click.Path(writable=True), help="Write JSON to file instead of stdout")
def fetch(biz, days, output):
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
        freshness = "fresh" if key_age < 3600 else "⚠ may be expired"
        click.echo(f"  Key extracted: {params['extracted_at']} ({age_str}) ({freshness})")
    if not params.get("pass_ticket") and not params.get("cookie"):
        click.echo("  ⚠ Missing pass_ticket/cookie in stored params — re-capture with updated proxy")
    click.echo()

    click.echo(f"Fetching articles from last {days} days...")
    fetcher = WeChatArticleFetcher(
        biz=params["__biz"],
        uin=params["uin"],
        key=params["key"],
        pass_ticket=params.get("pass_ticket", ""),
        appmsg_token=params.get("appmsg_token", ""),
        cookie=params.get("cookie", ""),
    )

    try:
        articles = fetcher.fetch_articles(days=days, callback=None)
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
        with open(output, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        click.echo(f"Written to {output}")
    else:
        for i, r in enumerate(result, 1):
            click.echo(f"{i}. {r['title']}")
            click.echo(f"   {r['url']}")
            click.echo(f"   {r['date']}")
            click.echo()


@main.command()
@click.option("--verbose", is_flag=True, help="Show full key/uin values")
def status(verbose):
    """Show stored WeChat account parameters."""
    store = ParamStore()
    accounts = store.list_accounts()

    if not accounts:
        click.echo("No stored accounts.")
        click.echo("Run 'start-proxy' and open a WeChat Official Account.")
        return

    click.echo(f"Stored accounts ({store._path}):\n")
    for a in accounts:
        biz = a["__biz"]
        extracted = a.get("extracted_at", "?")
        try:
            et = datetime.fromisoformat(extracted)
            age = (datetime.now(timezone.utc) - et).total_seconds()
            age_str = f"{age:.0f}s ago" if age < 3600 else f"{age / 3600:.1f}h ago"
            freshness = "fresh" if age < 3600 else "⚠ may be expired"
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
