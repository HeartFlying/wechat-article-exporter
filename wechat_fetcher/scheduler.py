"""定时任务调度器：定期检查参数健康状态并提醒。"""

import time
from datetime import datetime
from typing import Callable, Optional

from wechat_fetcher.storage import ParamStore, ParamStatus


class HealthCheckScheduler:
    """参数健康状态定时检查调度器。"""

    def __init__(self, check_interval_minutes: int = 30):
        """
        Args:
            check_interval_minutes: 检查间隔（分钟）
        """
        self.store = ParamStore()
        self.check_interval = check_interval_minutes * 60  # 转换为秒
        self._running = False
        self._callbacks: list[Callable] = []

    def add_callback(self, callback: Callable[[list], None]) -> None:
        """添加健康状态变化时的回调函数。

        Args:
            callback: 接收需要关注的账号列表的回调函数
        """
        self._callbacks.append(callback)

    def check_once(self, verbose: bool = False) -> list:
        """执行一次健康检查。

        Args:
            verbose: 是否打印详细信息

        Returns:
            需要关注的账号健康状态列表
        """
        all_health = self.store.check_all_health()
        to_notify = [h for h in all_health if h.needs_refresh]

        if verbose:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 健康检查完成")
            print(f"  总账号: {len(all_health)}, 需要关注: {len(to_notify)}")

            if to_notify:
                print("  需要关注的账号:")
                for h in to_notify:
                    icon = "✗" if h.is_expired else "!"
                    print(f"    {icon} {h.name or h.biz}: {h.message}")

        # 触发回调
        if to_notify and self._callbacks:
            for callback in self._callbacks:
                try:
                    callback(to_notify)
                except Exception as e:
                    print(f"回调执行失败: {e}")

        return to_notify

    def start(self, blocking: bool = False) -> None:
        """启动定时检查。

        Args:
            blocking: 是否阻塞当前线程
        """
        self._running = True
        print(f"启动定时健康检查，间隔: {self.check_interval // 60} 分钟")

        if blocking:
            self._run_loop()
        else:
            import threading
            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()

    def _run_loop(self) -> None:
        """运行检查循环。"""
        while self._running:
            self.check_once(verbose=True)

            # 等待下一次检查
            for _ in range(self.check_interval):
                if not self._running:
                    break
                time.sleep(1)

    def stop(self) -> None:
        """停止定时检查。"""
        self._running = False
        print("定时健康检查已停止")


def create_notifier(title_prefix: str = "WeChat Fetcher") -> Callable:
    """创建系统通知回调函数。

    Args:
        title_prefix: 通知标题前缀

    Returns:
        可用于 scheduler 的回调函数
    """
    def notify(health_list: list) -> None:
        """发送系统通知。"""
        expired = [h for h in health_list if h.is_expired]
        expiring = [h for h in health_list if h.status == ParamStatus.EXPIRING_SOON]

        messages = []
        if expired:
            messages.append(f"{len(expired)} 个账号已过期")
        if expiring:
            messages.append(f"{len(expiring)} 个账号即将过期")

        if not messages:
            return

        title = f"{title_prefix} - 参数过期提醒"
        message = "，".join(messages)

        # 尝试使用不同平台的通知方式
        try:
            # Windows
            import platform
            if platform.system() == "Windows":
                from win10toast import ToastNotifier
                toaster = ToastNotifier()
                toaster.show_toast(title, message, duration=10)
                return
        except ImportError:
            pass

        try:
            # macOS
            import os
            os.system(f"""
                      osascript -e 'display notification "{message}" with title "{title}"'
                      """)
            return
        except Exception:
            pass

        try:
            # Linux (notify-send)
            import os
            os.system(f'notify-send "{title}" "{message}"')
            return
        except Exception:
            pass

        # 回退到打印
        print(f"\n[!] {title}")
        print(f"    {message}\n")

    return notify


def run_scheduler_daemon(interval_minutes: int = 30, with_notify: bool = False) -> None:
    """运行定时检查守护进程。

    Args:
        interval_minutes: 检查间隔（分钟）
        with_notify: 是否启用系统通知
    """
    scheduler = HealthCheckScheduler(check_interval_minutes=interval_minutes)

    if with_notify:
        scheduler.add_callback(create_notifier())

    try:
        scheduler.start(blocking=True)
    except KeyboardInterrupt:
        scheduler.stop()


if __name__ == "__main__":
    # 命令行运行: python -m wechat_fetcher.scheduler
    import sys

    interval = 30
    notify = False

    if "--interval" in sys.argv:
        idx = sys.argv.index("--interval")
        if idx + 1 < len(sys.argv):
            interval = int(sys.argv[idx + 1])

    if "--notify" in sys.argv:
        notify = True

    run_scheduler_daemon(interval_minutes=interval, with_notify=notify)
