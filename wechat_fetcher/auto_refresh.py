"""自动刷新管理器：检测过期参数并自动触发 UI 更新。

工作流程：
1. 定期检查参数健康状态
2. 发现过期参数时，启动 UI 自动化
3. UI 自动化操作微信获取新参数
4. 验证新参数是否有效
5. 通知用户结果
"""

import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Callable, Optional

from wechat_fetcher.storage import ParamStore, ParamHealth, ParamStatus
from wechat_fetcher.ui_automation import (
    WeChatUIAutomation,
    AutomationResult,
    AutomationStatus,
)


class RefreshStrategy(Enum):
    """刷新策略。"""
    AUTO = "auto"           # 完全自动
    SEMI_AUTO = "semi"      # 半自动（需要用户确认）
    NOTIFY_ONLY = "notify"  # 仅通知


@dataclass
class RefreshTask:
    """刷新任务。"""
    biz: str
    account_name: str
    health: ParamHealth
    strategy: RefreshStrategy
    max_retries: int = 3


@dataclass
class RefreshResult:
    """刷新结果。"""
    task: RefreshTask
    success: bool
    message: str
    ui_result: Optional[AutomationResult] = None
    new_params: Optional[dict] = None
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


class AutoRefreshManager:
    """自动刷新管理器。"""

    # 默认配置
    DEFAULT_CHECK_INTERVAL = 300  # 5分钟检查一次
    PARAM_WAIT_TIMEOUT = 60  # 等待新参数超时（秒）

    def __init__(
        self,
        strategy: RefreshStrategy = RefreshStrategy.SEMI_AUTO,
        check_interval: int = DEFAULT_CHECK_INTERVAL,
    ):
        self.store = ParamStore()
        self.strategy = strategy
        self.check_interval = check_interval
        self._running = False
        self._progress_callbacks: list[Callable[[str], None]] = []
        self._result_callbacks: list[Callable[[RefreshResult], None]] = []

    def add_progress_callback(self, callback: Callable[[str], None]) -> None:
        """添加进度回调。"""
        self._progress_callbacks.append(callback)

    def add_result_callback(self, callback: Callable[[RefreshResult], None]) -> None:
        """添加结果回调。"""
        self._result_callbacks.append(callback)

    def _notify_progress(self, message: str) -> None:
        """通知进度。"""
        for callback in self._progress_callbacks:
            try:
                callback(message)
            except Exception:
                pass

    def _notify_result(self, result: RefreshResult) -> None:
        """通知结果。"""
        for callback in self._result_callbacks:
            try:
                callback(result)
            except Exception:
                pass

    def check_and_refresh(
        self,
        auto_execute: bool = False,
        account_filter: Optional[list] = None,
    ) -> list[RefreshResult]:
        """检查并刷新过期参数。

        Args:
            auto_execute: 是否自动执行 UI 自动化（无需确认）
            account_filter: 只检查指定账号列表

        Returns:
            刷新结果列表
        """
        results = []

        # 获取需要刷新的账号
        expired = self.store.get_expired_accounts()

        if account_filter:
            expired = [h for h in expired if h.biz in account_filter or h.name in account_filter]

        if not expired:
            self._notify_progress("没有需要刷新的账号")
            return results

        self._notify_progress(f"发现 {len(expired)} 个账号需要刷新参数")

        for health in expired:
            task = RefreshTask(
                biz=health.biz,
                account_name=health.name or health.biz,
                health=health,
                strategy=self.strategy,
            )

            result = self._execute_refresh(task, auto_execute)
            results.append(result)
            self._notify_result(result)

        return results

    def _execute_refresh(self, task: RefreshTask, auto_execute: bool) -> RefreshResult:
        """执行单个刷新任务。"""
        self._notify_progress(f"[{task.account_name}] 开始刷新参数...")

        # 根据策略决定是否执行
        if task.strategy == RefreshStrategy.NOTIFY_ONLY:
            return RefreshResult(
                task=task,
                success=False,
                message="策略设置为仅通知，跳过自动刷新",
            )

        if task.strategy == RefreshStrategy.SEMI_AUTO and not auto_execute:
            return RefreshResult(
                task=task,
                success=False,
                message="半自动模式：需要用户确认才能执行",
            )

        # 执行 UI 自动化
        try:
            ui_automation = WeChatUIAutomation()
            ui_automation.add_progress_callback(self._notify_progress)

            ui_result = ui_automation.run_automation(
                task.account_name,
                max_retries=task.max_retries,
            )

            if ui_result.status != AutomationStatus.SUCCESS:
                return RefreshResult(
                    task=task,
                    success=False,
                    message=f"UI 自动化失败: {ui_result.message}",
                    ui_result=ui_result,
                )

            # 等待并验证新参数
            self._notify_progress("UI 自动化完成，等待参数更新...")
            new_params = self._wait_for_new_params(task.biz)

            if new_params:
                return RefreshResult(
                    task=task,
                    success=True,
                    message="参数刷新成功",
                    ui_result=ui_result,
                    new_params=new_params,
                )
            else:
                return RefreshResult(
                    task=task,
                    success=False,
                    message="UI 自动化完成，但未检测到新参数",
                    ui_result=ui_result,
                )

        except Exception as e:
            return RefreshResult(
                task=task,
                success=False,
                message=f"刷新异常: {e}",
            )

    def _wait_for_new_params(self, biz: str) -> Optional[dict]:
        """等待新参数被捕获。

        Args:
            biz: 公众号 biz

        Returns:
            新参数或 None
        """
        start_time = time.time()

        while time.time() - start_time < self.PARAM_WAIT_TIMEOUT:
            # 检查参数是否有效（通过 API 验证）
            current_health = self.store.check_health(biz, use_cache=False)

            # 如果参数变为有效，说明更新成功
            if current_health.is_valid:
                return self.store.load(biz)

            time.sleep(2)

        return None

    def start_daemon(self, auto_execute: bool = False) -> None:
        """启动守护进程。

        Args:
            auto_execute: 是否自动执行（无需确认）
        """
        self._running = True
        self._notify_progress("自动刷新守护进程已启动")

        while self._running:
            try:
                self.check_and_refresh(auto_execute=auto_execute)
            except Exception as e:
                self._notify_progress(f"检查异常: {e}")

            # 等待下一次检查
            for _ in range(self.check_interval):
                if not self._running:
                    break
                time.sleep(1)

    def stop_daemon(self) -> None:
        """停止守护进程。"""
        self._running = False
        self._notify_progress("自动刷新守护进程已停止")

    def refresh_single(
        self,
        account_name: str,
        wait_for_params: bool = True,
    ) -> RefreshResult:
        """刷新单个账号。

        Args:
            account_name: 公众号名称
            wait_for_params: 是否等待新参数

        Returns:
            RefreshResult
        """
        # 查找账号
        params = self.store.load_by_name(account_name)
        if not params:
            # 尝试通过 biz 查找
            accounts = self.store.list_accounts()
            for acc in accounts:
                if acc.get("name") == account_name:
                    params = self.store.load(acc["__biz"])
                    break

        if not params:
            return RefreshResult(
                task=RefreshTask(
                    biz="",
                    account_name=account_name,
                    health=None,
                    strategy=self.strategy,
                ),
                success=False,
                message=f"未找到账号: {account_name}",
            )

        biz = params.get("__biz", "")
        health = self.store.check_health(biz)

        task = RefreshTask(
            biz=biz,
            account_name=account_name,
            health=health,
            strategy=RefreshStrategy.AUTO,  # 单个刷新强制自动
        )

        return self._execute_refresh(task, auto_execute=True)


def create_refresh_notifier() -> Callable[[RefreshResult], None]:
    """创建刷新结果通知器。"""
    def notify(result: RefreshResult) -> None:
        task = result.task
        if result.success:
            title = "✓ 参数刷新成功"
            message = f"{task.account_name}: {result.message}"
            color = "green"
        else:
            title = "✗ 参数刷新失败"
            message = f"{task.account_name}: {result.message}"
            color = "red"

        print(f"\n[{title}] {message}")

        # 尝试系统通知
        try:
            import platform
            if platform.system() == "Windows":
                try:
                    from win10toast import ToastNotifier
                    toaster = ToastNotifier()
                    toaster.show_toast(title, message, duration=5)
                except ImportError:
                    pass
        except Exception:
            pass

    return notify


if __name__ == "__main__":
    # 命令行运行
    import sys

    def print_progress(msg):
        print(f"[自动刷新] {msg}")

    manager = AutoRefreshManager()
    manager.add_progress_callback(print_progress)
    manager.add_result_callback(create_refresh_notifier())

    if "--daemon" in sys.argv:
        # 守护进程模式
        auto = "--auto" in sys.argv
        manager.start_daemon(auto_execute=auto)
    elif len(sys.argv) > 1:
        # 刷新单个账号
        account = sys.argv[1]
        result = manager.refresh_single(account)
        print(f"\n结果: {'成功' if result.success else '失败'}")
        print(f"消息: {result.message}")
    else:
        # 检查并刷新所有过期账号
        results = manager.check_and_refresh(auto_execute=True)
        print(f"\n完成: 处理了 {len(results)} 个账号")
