import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import click

from wechat_fetcher.config import get_config
from wechat_fetcher.storage import ParamStore, ParamStatus
from wechat_fetcher.fetcher import WeChatArticleFetcher, KeyExpiredError
from wechat_fetcher.downloader import ArticleDownloader
from wechat_fetcher.dedup import DedupIndex
from wechat_fetcher.workflow import WorkflowEngine


def _get_resource_path(relative_path: str) -> str:
    """获取资源文件的绝对路径，兼容 PyInstaller 单文件模式。

    PyInstaller 单文件模式会将文件解压到临时目录，通过 sys._MEIPASS 访问。
    普通模式下直接使用文件所在目录。
    """
    if hasattr(sys, '_MEIPASS'):
        # PyInstaller 单文件模式
        return os.path.join(sys._MEIPASS, relative_path)
    else:
        # 普通模式
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)


def _find_mitmdump() -> str:
    """查找 mitmdump 可执行文件。"""
    # 首先检查 PATH
    if os.name == "nt":
        import shutil
        mitmdump_path = shutil.which("mitmdump")
        if mitmdump_path:
            return mitmdump_path
    else:
        mitmdump_path = subprocess.run(
            ["which", "mitmdump"], capture_output=True, text=True
        ).stdout.strip()
        if mitmdump_path:
            return mitmdump_path

    # 检查虚拟环境 Scripts/bin 目录
    scripts_dir = os.path.join(os.path.dirname(sys.executable), "Scripts") if os.name == "nt" \
        else os.path.join(os.path.dirname(sys.executable), "..", "bin")
    exe = "mitmdump.exe" if os.name == "nt" else "mitmdump"
    path = os.path.join(scripts_dir, exe)
    if os.path.isfile(path):
        return path

    return "mitmdump"


@click.group()
@click.version_option(version="0.2.0", prog_name="wechat-fetcher")
def main():
    """WeChat Official Account article URL fetcher.

    微信公众号文章抓取工具。通过 MITM 代理拦截微信客户端 HTTPS 流量提取认证参数，
    进而调用微信文章列表 API 抓取文章 URL，并支持一键下载为 Markdown。
    """
    pass


@main.command()
@click.option("--port", default=8080, help="代理端口 (默认: 8080)")
@click.option("--listen-host", default="0.0.0.0", help="监听地址 (默认: 0.0.0.0)")
@click.option("--show-ip", is_flag=True, help="显示本地 IP 用于手机代理配置")
@click.option("--verbose", "-v", is_flag=True, help="显示详细调试信息（包括名称解析过程）")
def start_proxy(port, listen_host, show_ip, verbose):
    """启动 MITM 代理，拦截微信请求并提取认证参数。"""
    config = get_config()

    click.echo(click.style("WeChat Article Fetcher Proxy", fg="cyan", bold=True))
    click.echo("=" * 60)
    click.echo(f"代理监听: {listen_host}:{port}")
    click.echo(f"数据目录: {config.data_dir}")
    if verbose:
        click.echo(click.style("调试模式: 已启用", fg="yellow"))
    click.echo()

    if show_ip:
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            click.echo(click.style(f"本机 IP: {local_ip}", fg="green"))
        except Exception:
            click.echo(click.style("无法获取本机 IP", fg="yellow"))
        click.echo()

    click.echo(click.style("使用说明:", fg="cyan", bold=True))
    if show_ip:
        click.echo(click.style(" [手机模式]", fg="magenta"))
        click.echo("1. 配置手机 Wi-Fi 代理:")
        click.echo(f"   服务器: <电脑IP>  端口: {port}")
        click.echo()
        click.echo("2. 安装 mitmproxy CA 证书:")
        click.echo("   手机访问 http://mitm.it (需先开启代理)")
        click.echo("   iOS: 设置 > 通用 > VPN与设备管理")
        click.echo("   Android: 设置 > 安全 > 从存储安装")
        click.echo()
        click.echo("3. 打开微信，找到目标公众号")
        click.echo("4. 点击'全部消息'并下滑加载更多")
    else:
        click.echo(click.style(" [桌面模式]", fg="magenta"))
        click.echo("1. 设置 Windows 系统代理:")
        click.echo(f"   Win+I > 网络和 Internet > 代理 > 手动")
        click.echo(f"   地址: 127.0.0.1  端口: {port}")
        click.echo()
        click.echo("2. 安装 mitmproxy CA 证书:")
        click.echo("   浏览器访问 http://mitm.it (需先开启代理)")
        click.echo("   下载 Windows 证书并安装到:")
        click.echo("   '受信任的根证书颁发机构'")
        click.echo()
        click.echo("3. 重启微信桌面版 (完全退出后重新打开)")
        click.echo("4. 打开目标公众号，点击'全部消息'并下滑加载")
    click.echo()
    click.echo(click.style("5. 观察此窗口的 'Captured params' 日志", fg="green"))
    if verbose:
        click.echo(click.style("6. 调试模式：将显示名称解析过程的详细信息", fg="yellow"))
    click.echo()
    click.echo(click.style("按 Ctrl+C 停止代理", fg="yellow"))
    click.echo("=" * 60)
    click.echo()

    # 使用 mitmproxy 的 Python API 直接启动代理
    try:
        _run_mitmproxy_proxy(port, listen_host, verbose)
    except KeyboardInterrupt:
        click.echo(click.style("\n代理已停止", fg="yellow"))
    except Exception as e:
        click.echo(click.style(f"错误: {e}", fg="red"), err=True)
        sys.exit(1)


def _run_mitmproxy_proxy(port: int, listen_host: str, verbose: bool = False):
    """使用 mitmproxy 的 dump 模式启动代理。"""
    import asyncio
    from mitmproxy.tools import dump
    from mitmproxy import options
    from wechat_fetcher.proxy_addon import WeChatInterceptor

    # 创建配置选项
    opts = options.Options(
        listen_port=port,
        listen_host=listen_host,
    )

    async def main():
        # 创建 dump master（不需要额外的 proxy server）
        m = dump.DumpMaster(opts)

        # 设置日志级别
        if verbose:
            m.options.termlog_verbosity = "debug"  # 设置详细日志级别

        # 添加我们的拦截器
        interceptor = WeChatInterceptor(verbose=verbose)
        m.addons.add(interceptor)

        # 启动代理
        try:
            await m.run()
        except KeyboardInterrupt:
            pass
        finally:
            await m.shutdown()

    # 运行异步主函数
    asyncio.run(main())


@main.command()
@click.option("--biz", required=True, help="目标公众号的 __biz 值")
@click.option("--days", type=int, help="抓取最近 N 天的文章")
@click.option("--from", "from_date", help="开始日期 (YYYY-MM-DD)")
@click.option("--to", "to_date", help="结束日期 (YYYY-MM-DD)")
@click.option("--output", "-o", type=click.Path(writable=True), help="输出 JSON 文件路径")
def fetch(biz, days, from_date, to_date, output):
    """从微信公众号抓取文章 URL 列表。"""
    store = ParamStore()
    params = store.load(biz)

    if params is None:
        click.echo(click.style(f"错误: 未找到 __biz={biz} 的存储参数", fg="red"), err=True)
        accounts = store.list_accounts()
        if accounts:
            if len(accounts) == 1:
                click.echo(f"您是否指: {accounts[0]['__biz']} ?", err=True)
            click.echo("\n已存储的账号:", err=True)
            for a in accounts:
                click.echo(f"  {a['__biz']}  ({a.get('extracted_at', '?')})", err=True)
        else:
            click.echo("请先运行 'start-proxy'，然后在微信中打开目标公众号", err=True)
        sys.exit(1)

    # 检查 key 新鲜度
    key_age = None
    if params.get("extracted_at"):
        try:
            extracted = datetime.fromisoformat(params["extracted_at"])
            key_age = (datetime.now(timezone.utc) - extracted).total_seconds()
        except (ValueError, TypeError):
            pass

    click.echo(click.style(f"账号: {biz}", fg="cyan", bold=True))
    if key_age is not None:
        age_str = f"{key_age:.0f}秒前" if key_age < 3600 else f"{key_age / 3600:.1f}小时前"
        freshness = click.style("有效", fg="green") if key_age < 3600 else click.style("[!] 可能已过期", fg="yellow")
        click.echo(f"  Key 提取时间: {params['extracted_at']} ({age_str}) {freshness}")
    if not params.get("pass_ticket") and not params.get("cookie"):
        click.echo(click.style("  [!] 缺少 pass_ticket/cookie - 建议重新捕获", fg="yellow"))
    click.echo()

    date_label = f"最近 {days} 天" if days else f"{from_date} 至 {to_date}"
    click.echo(f"正在抓取 {date_label} 的文章...")

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
        click.echo(click.style(f"错误: {e}", fg="red"), err=True)
        sys.exit(1)

    click.echo(click.style(f"\n找到 {len(articles)} 篇文章\n", fg="green"))

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
            click.echo(f"输出为目录，写入到: {out_path}")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        click.echo(click.style(f"已保存到: {out_path}", fg="green"))
    else:
        for i, r in enumerate(result, 1):
            click.echo(f"{i}. {r['title']}")
            click.echo(f"   {r['url']}")
            click.echo(f"   {r['date']}")
            click.echo()


@main.command()
@click.option("--verbose", "-v", is_flag=True, help="显示完整的 key/uin 值")
@click.option("--health", "-h", is_flag=True, help="显示详细的健康检查结果")
def status(verbose, health):
    """查看已存储的微信账号参数和去重索引状态。"""
    config = get_config()
    store = ParamStore()
    accounts = store.list_accounts()

    click.echo(click.style("数据目录:", fg="cyan") + f" {config.data_dir}")
    click.echo()

    if not accounts:
        click.echo(click.style("暂无存储的账号", fg="yellow"))
        click.echo("运行 'start-proxy' 并在微信中打开公众号以捕获参数")
    else:
        click.echo(click.style(f"已存储账号 ({store._accounts_dir}):\n", fg="cyan", bold=True))

        # 使用健康检查获取详细状态
        health_list = store.check_all_health()
        health_map = {h.biz: h for h in health_list}

        expired_count = 0
        expiring_count = 0
        valid_count = 0

        for a in accounts:
            biz = a["__biz"]
            name = a.get("name", "")
            extracted = a.get("extracted_at", "?")

            # 获取健康状态
            h = health_map.get(biz)
            if h:
                if h.is_expired:
                    expired_count += 1
                    status_color = "red"
                    status_icon = "✗"
                elif h.status == ParamStatus.EXPIRING_SOON:
                    expiring_count += 1
                    status_color = "yellow"
                    status_icon = "!"
                else:
                    valid_count += 1
                    status_color = "green"
                    status_icon = "✓"

                remaining_str = f"[{h.remaining_seconds/60:.0f}分钟]" if h.remaining_seconds > 0 else "[已过期]"
            else:
                status_color = "red"
                status_icon = "?"
                remaining_str = ""

            # 显示格式: 公众号名称 (biz)
            if name:
                click.echo(f"  {click.style(status_icon, fg=status_color)} {click.style(name, fg='green', bold=True)} {click.style(f'({biz})', fg='cyan')}")
            else:
                click.echo(f"  {click.style(status_icon, fg=status_color)} {click.style(biz, fg='cyan')}")

            if health and h:
                click.echo(f"    状态: {click.style(h.message, fg=status_color)}")
            else:
                click.echo(f"    提取时间: {extracted} {click.style(remaining_str, fg=status_color)}")

            if verbose:
                full = store.load(biz)
                if full:
                    click.echo(f"    uin: {full.get('uin', '?')}")
                    click.echo(f"    key: {full.get('key', '?')}")
            click.echo()

        # 汇总
        click.echo(click.style("状态汇总:", fg="cyan", bold=True))
        click.echo(f"  {click.style('✓', fg='green')} 有效: {valid_count}  {click.style('!', fg='yellow')} 即将过期: {expiring_count}  {click.style('✗', fg='red')} 已过期: {expired_count}")
        click.echo()

        # 提醒
        if expired_count > 0:
            click.echo(click.style(f"[!] 有 {expired_count} 个账号参数已过期，建议运行 start-proxy 重新获取", fg="red"))
        if expiring_count > 0:
            click.echo(click.style(f"[!] 有 {expiring_count} 个账号参数即将过期，请及时刷新", fg="yellow"))

    dedup = DedupIndex()
    ds = dedup.stats()
    click.echo(click.style(f"去重索引统计:", fg="cyan", bold=True))
    click.echo(f"  文章标题: {ds['total_titles']}  文章URL: {ds['total_urls']}  账号数: {ds['accounts']}")

    # 显示每个账号的去重统计
    dedup_accounts = dedup.list_accounts()
    if dedup_accounts:
        click.echo(click.style(f"\n各账号去重详情:", fg="cyan", bold=True))
        for acc in dedup_accounts:
            click.echo(f"  {acc['name']}: {acc['titles']} 个标题, {acc['urls']} 个URL")


@main.command()
@click.option("--input", "input_file", required=True, help="文章列表 JSON 文件路径")
@click.option("--output-dir", "-o", help="输出目录 (默认: ~/.wechat-fetcher/data/articles)")
@click.option("--cookie", help="微信认证 Cookie")
@click.option("--start", default=0, help="起始索引 (默认: 0)")
@click.option("--end", type=int, help="结束索引 (默认: 全部)")
@click.option("--account-name", "-n", help="公众号名称，用于创建子目录")
def download(input_file, output_dir, cookie, start, end, account_name):
    """下载文章并转换为 Markdown。"""
    downloader = ArticleDownloader(output_dir=output_dir, cookie=cookie)

    if not os.path.exists(input_file):
        click.echo(click.style(f"错误: 文件不存在: {input_file}", fg="red"), err=True)
        sys.exit(1)

    articles = downloader.load_articles(input_file)
    click.echo(f"从 {input_file} 加载了 {len(articles)} 篇文章")

    if start >= len(articles):
        click.echo(click.style(f"错误: 起始索引 {start} 超出范围", fg="red"), err=True)
        sys.exit(1)

    dedup = DedupIndex()
    results = downloader.download_all(articles, start=start, end=end, dedup=dedup,
                                      account_name=account_name)

    if results["failed"]:
        click.echo(click.style("\n下载失败的文章:", fg="red"), err=True)
        for item in results["failed"]:
            click.echo(f"  - {item['title']}", err=True)
            click.echo(f"    {item['url']}", err=True)


@main.command()
@click.option("--biz", multiple=True, help="目标账号 __biz (可多次指定)")
@click.option("--all", "all_accounts", is_flag=True, help="处理所有已存储账号")
@click.option("--days", type=int, help="抓取最近 N 天的文章")
@click.option("--from", "from_date", help="开始日期 (YYYY-MM-DD)")
@click.option("--to", "to_date", help="结束日期 (YYYY-MM-DD)")
@click.option("--output-dir", "-o", help="输出目录")
@click.option("--cookie", help="微信认证 Cookie")
@click.option("--wait-proxy", is_flag=True, help="等待代理捕获参数后再开始")
def run(biz, all_accounts, days, from_date, to_date, output_dir, cookie, wait_proxy):
    """一键工作流: 抓取 → 去重 → 下载 (支持多账号)。"""
    if not biz and not all_accounts:
        click.echo(click.style("错误: 请指定 --biz 或 --all", fg="red"), err=True)
        sys.exit(1)

    store = ParamStore()
    if all_accounts:
        biz_list = [a["__biz"] for a in store.list_accounts()]
        if not biz_list:
            click.echo(click.style("错误: 无已存储账号", fg="red"), err=True)
            click.echo("请先运行 start-proxy 并打开目标公众号", err=True)
            sys.exit(1)
        click.echo(f"将处理 {len(biz_list)} 个账号: {', '.join(biz_list)}")
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

    click.echo()
    click.echo("=" * 50)
    click.echo(click.style("工作流完成", fg="cyan", bold=True))
    click.echo(f"  成功: {click.style(str(total_success), fg='green')}")
    click.echo(f"  跳过: {click.style(str(total_skipped), fg='yellow')}")
    click.echo(f"  失败: {click.style(str(total_failed), fg='red')}")
    if total_errors:
        click.echo(f"  参数错误: {click.style(str(total_errors), fg='red')}")
        for e in results["errors"]:
            click.echo(f"    - {e['biz']}: {e['reason']}")

    if total_errors == len(biz_list):
        sys.exit(1)
    elif total_errors > 0 or total_failed > 0:
        sys.exit(2)


@main.command()
def info():
    """显示工具信息和数据目录位置。"""
    config = get_config()
    store = ParamStore()

    click.echo(click.style("WeChat Fetcher", fg="cyan", bold=True))
    click.echo("=" * 50)
    click.echo(f"版本: 0.2.0")
    click.echo(f"数据目录: {config.data_dir}")
    click.echo(f"配置目录: {config.config_dir}")
    click.echo()
    click.echo(click.style("存储结构:", fg="cyan", bold=True))
    click.echo(f"  账号数据: {store._accounts_dir}/")
    click.echo(f"    - <公众号名称>/")
    click.echo(f"      - params.json       # 认证参数")
    click.echo(f"      - dedup_index.json  # 去重索引")
    click.echo(f"      - articles/         # 下载的文章")
    click.echo()
    click.echo(click.style("环境变量:", fg="cyan"))
    click.echo("  WECHAT_FETCHER_DATA   - 自定义数据目录")
    click.echo("  WECHAT_FETCHER_CONFIG - 自定义配置目录")


@main.command()
@click.option("--biz", help="检查指定账号的健康状态")
@click.option("--notify", is_flag=True, help="仅显示需要关注的账号（已过期或即将过期）")
def health(biz, notify):
    """检查账号参数的健康状态和有效期。"""
    store = ParamStore()

    if biz:
        # 检查指定账号
        h = store.check_health(biz)
        _display_health(h)
    else:
        # 检查所有账号
        all_health = store.check_all_health()

        if notify:
            # 只显示需要关注的
            to_notify = [h for h in all_health if h.needs_refresh]
            if not to_notify:
                click.echo(click.style("✓ 所有账号参数均有效", fg="green"))
                return
            click.echo(click.style(f"需要关注的账号 ({len(to_notify)}个):\n", fg="yellow", bold=True))
            for h in to_notify:
                _display_health(h)
                click.echo()
        else:
            # 显示所有
            if not all_health:
                click.echo(click.style("暂无存储的账号", fg="yellow"))
                return

            valid = [h for h in all_health if h.is_valid]
            expired = [h for h in all_health if h.is_expired]
            expiring = [h for h in all_health if h.status == ParamStatus.EXPIRING_SOON]

            click.echo(click.style("账号健康检查报告\n", fg="cyan", bold=True))
            click.echo("=" * 50)

            if valid:
                click.echo(click.style(f"\n✓ 有效账号 ({len(valid)}个):", fg="green", bold=True))
                for h in valid:
                    click.echo(f"  {h.name or h.biz}: 还剩 {h.remaining_seconds/60:.0f} 分钟")

            if expiring:
                click.echo(click.style(f"\n! 即将过期 ({len(expiring)}个):", fg="yellow", bold=True))
                for h in expiring:
                    click.echo(f"  {h.name or h.biz}: 还剩 {h.remaining_seconds/60:.0f} 分钟")

            if expired:
                click.echo(click.style(f"\n✗ 已过期 ({len(expired)}个):", fg="red", bold=True))
                for h in expired:
                    click.echo(f"  {h.name or h.biz}: 已过期 {abs(h.remaining_seconds)/60:.0f} 分钟")

            click.echo("\n" + "=" * 50)
            click.echo(click.style("建议操作:", fg="cyan", bold=True))
            if expired:
                click.echo(f"  1. 运行 {click.style('start-proxy', fg='cyan')} 重新获取已过期账号的参数")
            if expiring:
                click.echo(f"  2. 在参数过期前运行 {click.style('start-proxy', fg='cyan')} 刷新")
            if valid:
                click.echo(f"  3. 有效账号可直接运行 {click.style('run --all', fg='cyan')} 抓取文章")


def _display_health(h):
    """显示单个账号的健康状态。"""
    from wechat_fetcher.storage import ParamStatus

    if h.status == ParamStatus.NOT_FOUND:
        click.echo(click.style(f"✗ 账号不存在: {h.biz}", fg="red"))
        return

    # 状态颜色
    if h.is_expired:
        color = "red"
        icon = "✗"
    elif h.status == ParamStatus.EXPIRING_SOON:
        color = "yellow"
        icon = "!"
    else:
        color = "green"
        icon = "✓"

    click.echo(f"{click.style(icon, fg=color)} {click.style(h.name or h.biz, fg='cyan', bold=True)}")
    click.echo(f"  状态: {click.style(h.message, fg=color)}")

    if h.extracted_at:
        click.echo(f"  提取时间: {h.extracted_at.strftime('%Y-%m-%d %H:%M:%S')}")
    if h.expires_at:
        click.echo(f"  过期时间: {h.expires_at.strftime('%Y-%m-%d %H:%M:%S')}")


@main.command()
@click.option("--name", "-n", help="要删除的公众号名称 (不指定则删除所有)")
@click.confirmation_option(prompt="确定要删除参数吗?")
def clear(name):
    """清除存储的参数或去重索引。"""
    store = ParamStore()

    if name:
        if store.delete(name):
            click.echo(click.style(f"已删除账号: {name}", fg="green"))
        else:
            click.echo(click.style(f"账号不存在: {name}", fg="yellow"))
    else:
        # 删除所有参数
        accounts = store.list_accounts()
        for a in accounts:
            account_name = a.get("name", a.get("__biz", ""))
            store.delete(account_name)
        click.echo(click.style(f"已删除 {len(accounts)} 个账号的参数", fg="green"))


@main.command()
@click.option("--interval", "-i", default=30, help="检查间隔（分钟，默认: 30）")
@click.option("--notify", "-n", is_flag=True, help="启用系统通知（需要 win10toast）")
@click.option("--once", is_flag=True, help="只执行一次检查，不启动守护进程")
def watch(interval, notify, once):
    """启动定时健康检查守护进程，监控参数过期状态。"""
    from wechat_fetcher.scheduler import HealthCheckScheduler, create_notifier

    scheduler = HealthCheckScheduler(check_interval_minutes=interval)

    if notify:
        try:
            scheduler.add_callback(create_notifier())
            click.echo(click.style("已启用系统通知", fg="green"))
        except Exception as e:
            click.echo(click.style(f"通知功能初始化失败: {e}", fg="yellow"))

    if once:
        click.echo("执行一次健康检查...")
        to_notify = scheduler.check_once(verbose=True)
        if not to_notify:
            click.echo(click.style("✓ 所有账号参数均有效", fg="green"))
        return

    click.echo(click.style(f"启动定时健康检查，间隔: {interval} 分钟", fg="cyan", bold=True))
    click.echo(click.style("按 Ctrl+C 停止", fg="yellow"))
    click.echo("=" * 50)

    try:
        scheduler.start(blocking=True)
    except KeyboardInterrupt:
        scheduler.stop()
        click.echo(click.style("\n已停止监控", fg="yellow"))


@main.command()
@click.option("--account", "-a", help="指定要刷新的公众号名称（不指定则刷新所有过期账号）")
@click.option("--auto", "auto_execute", is_flag=True, help="自动执行 UI 自动化（无需确认）")
@click.option("--daemon", "-d", is_flag=True, help="以守护进程模式运行，定期检查并刷新")
@click.option("--interval", "-i", default=5, help="守护进程检查间隔（分钟，默认: 5）")
@click.option("--strategy", "-s", type=click.Choice(["auto", "semi", "notify"]),
              default="semi", help="刷新策略: auto=完全自动, semi=半自动(需确认), notify=仅通知")
def refresh(account, auto_execute, daemon, interval, strategy):
    """自动刷新过期参数：检测过期 → UI 自动化 → 获取新参数。

    需要安装依赖: pip install uiautomation psutil

    示例:
        wechat-fetcher refresh --account "公众号名称" --auto
        wechat-fetcher refresh --daemon --auto --interval 10
    """
    click.echo(click.style("[!] UI 自动化刷新功能暂不可用", fg="yellow", bold=True))
    click.echo("请使用 'start-proxy' 命令手动捕获参数")
    return

    # 以下代码暂时禁用
    # from wechat_fetcher.auto_refresh import (
    #     AutoRefreshManager,
    #     RefreshStrategy,
    #     create_refresh_notifier,
    # )
    #
    # # 转换策略
    # strategy_map = {
    #     "auto": RefreshStrategy.AUTO,
    #     "semi": RefreshStrategy.SEMI_AUTO,
    #     "notify": RefreshStrategy.NOTIFY_ONLY,
    # }
    # refresh_strategy = strategy_map.get(strategy, RefreshStrategy.SEMI_AUTO)
    #
    # # 检查依赖
    # try:
    #     import uiautomation
    #     import psutil
    # except ImportError as e:
    #     click.echo(click.style(f"缺少依赖: {e}", fg="red"), err=True)
    #     click.echo("请安装: pip install uiautomation psutil", err=True)
    #     sys.exit(1)
    #
    # manager = AutoRefreshManager(
    #     strategy=refresh_strategy,
    #     check_interval=interval * 60,
    # )
    #
    # # 添加进度回调
    # def progress_callback(msg):
    #     click.echo(f"[自动刷新] {msg}")
    #
    # manager.add_progress_callback(progress_callback)
    # manager.add_result_callback(create_refresh_notifier())
    #
    # if daemon:
    #     # 守护进程模式
    #     click.echo(click.style("启动自动刷新守护进程", fg="cyan", bold=True))
    #     click.echo(f"策略: {strategy}, 检查间隔: {interval} 分钟")
    #     click.echo(click.style("按 Ctrl+C 停止", fg="yellow"))
    #     click.echo("=" * 50)
    #
    #     try:
    #         manager.start_daemon(auto_execute=auto_execute)
    #     except KeyboardInterrupt:
    #         manager.stop_daemon()
    #         click.echo(click.style("\n已停止守护进程", fg="yellow"))
    #
    # elif account:
    #     # 刷新单个账号
    #     click.echo(f"正在刷新账号: {account}")
    #     result = manager.refresh_single(account)
    #
    #     if result.success:
    #         click.echo(click.style(f"✓ 刷新成功: {result.message}", fg="green"))
    #     else:
    #         click.echo(click.style(f"✗ 刷新失败: {result.message}", fg="red"))
    #         sys.exit(1)
    #
    # else:
    #     # 刷新所有过期账号
    #     click.echo("检查并刷新所有过期账号...")
    #     results = manager.check_and_refresh(auto_execute=auto_execute)
    #
    #     if not results:
    #         click.echo(click.style("✓ 没有需要刷新的账号", fg="green"))
    #         return
    #
    #     success_count = sum(1 for r in results if r.success)
    #     fail_count = len(results) - success_count
    #
    #     click.echo("\n" + "=" * 50)
    #     click.echo(click.style("刷新结果汇总:", fg="cyan", bold=True))
    #     click.echo(f"  成功: {click.style(str(success_count), fg='green')}")
    #     click.echo(f"  失败: {click.style(str(fail_count), fg='red')}")
    #
    #     if fail_count > 0:
    #         click.echo("\n失败的账号:")
    #         for r in results:
    #             if not r.success:
    #                 click.echo(f"  - {r.task.account_name}: {r.message}")
    #         sys.exit(1)


if __name__ == "__main__":
    main()
