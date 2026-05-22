"""微信桌面版 UI 自动化模块。

用于自动操作微信桌面版获取公众号参数。
使用 pywinauto 实现，支持新版微信 (Weixin.exe)。
"""

import os
import subprocess
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional


class UIAutomationError(Exception):
    """UI 自动化错误。"""
    pass


class WeChatNotFoundError(UIAutomationError):
    """未找到微信窗口。"""
    pass


class NavigationError(UIAutomationError):
    """导航失败。"""
    pass


class AutomationStatus(Enum):
    """自动化状态。"""
    IDLE = "idle"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"


@dataclass
class AutomationResult:
    """自动化执行结果。"""
    status: AutomationStatus
    message: str
    duration: float
    retry_count: int = 0


class WeChatUIAutomation:
    """微信桌面版 UI 自动化控制器。"""

    # 默认超时时间（秒）
    DEFAULT_TIMEOUT = 60
    # 操作间隔（秒）
    ACTION_DELAY = 1.5
    # 微信进程名（支持 WeChat.exe 和 Weixin.exe）
    WECHAT_PROCESS_NAMES = ["WeChat.exe", "Weixin.exe"]
    # 微信窗口类名（支持多种版本）
    WECHAT_WINDOW_CLASSES = ["WeChatMainWndForPC", "Qt51514QWindowIcon"]

    def __init__(self, timeout: int = DEFAULT_TIMEOUT):
        self.timeout = timeout
        self._status = AutomationStatus.IDLE
        self._progress_callbacks: list[Callable[[str], None]] = []
        self._window = None
        self._pywinauto_available = self._check_pywinauto()

    def _check_pywinauto(self) -> bool:
        """检查是否可用 pywinauto 库。"""
        try:
            from pywinauto import Desktop
            return True
        except ImportError:
            return False

    def add_progress_callback(self, callback: Callable[[str], None]) -> None:
        """添加进度回调函数。"""
        self._progress_callbacks.append(callback)

    def _notify_progress(self, message: str) -> None:
        """通知进度更新。"""
        for callback in self._progress_callbacks:
            try:
                callback(message)
            except Exception:
                pass

    def _get_window(self):
        """获取微信主窗口。"""
        if not self._pywinauto_available:
            return None

        from pywinauto import Desktop

        # 尝试通过窗口标题查找微信主窗口
        desktop = Desktop(backend='win32')
        windows = desktop.windows()

        for w in windows:
            try:
                text = w.window_text()
                class_name = w.class_name()

                # 匹配窗口标题为"微信"且类名在支持列表中
                if text == "微信" and class_name in self.WECHAT_WINDOW_CLASSES:
                    self._notify_progress(f"找到微信窗口 (类名: {class_name})")
                    return w
            except:
                pass

        self._notify_progress("未找到微信窗口")
        return None

    def is_wechat_running(self) -> bool:
        """检查微信是否在运行。"""
        import psutil
        for proc in psutil.process_iter(['name']):
            try:
                if proc.info['name'] in self.WECHAT_PROCESS_NAMES:
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return False

    def launch_wechat(self) -> bool:
        """启动微信。"""
        self._notify_progress("正在启动微信...")

        if self.is_wechat_running():
            self._notify_progress("微信已在运行")
            return True

        try:
            # 尝试启动微信
            # 常见安装路径
            possible_paths = [
                r"C:\Program Files\Tencent\WeChat\WeChat.exe",
                r"C:\Program Files (x86)\Tencent\WeChat\WeChat.exe",
                r"C:\Program Files\Tencent\Weixin\Weixin.exe",
                r"C:\Program Files (x86)\Tencent\Weixin\Weixin.exe",
            ]

            wechat_path = None
            for path in possible_paths:
                if os.path.exists(path):
                    wechat_path = path
                    break

            if not wechat_path:
                # 尝试从注册表查找
                try:
                    import winreg
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                       r"Software\Tencent\WeChat") as key:
                        wechat_path, _ = winreg.QueryValueEx(key, "InstallPath")
                        wechat_path = os.path.join(wechat_path, "WeChat.exe")
                except Exception:
                    pass

            if not wechat_path or not os.path.exists(wechat_path):
                raise WeChatNotFoundError("无法找到微信安装路径")

            subprocess.Popen([wechat_path], shell=True)

            # 等待微信启动
            start_time = time.time()
            while time.time() - start_time < self.timeout:
                if self.is_wechat_running():
                    time.sleep(3)  # 等待窗口加载
                    self._notify_progress("微信启动成功")
                    return True
                time.sleep(1)

            raise WeChatNotFoundError("微信启动超时")

        except Exception as e:
            raise WeChatNotFoundError(f"启动微信失败: {e}")

    def activate_wechat(self) -> bool:
        """激活微信窗口。"""
        self._notify_progress("正在激活微信窗口...")

        window = self._get_window()
        if not window:
            return False

        try:
            # 使用 pywinauto 激活窗口
            window.set_focus()
            time.sleep(self.ACTION_DELAY)
            return True
        except Exception as e:
            self._notify_progress(f"激活窗口失败: {e}")
            return False

    def navigate_to_contacts(self) -> bool:
        """导航到通讯录。"""
        self._notify_progress("正在打开通讯录...")

        if not self._pywinauto_available:
            return False

        window = self._get_window()
        if not window:
            return False

        try:
            # 确保窗口有焦点
            window.set_focus()
            time.sleep(0.5)

            # 新版微信使用 Qt 渲染，传统的 UI 自动化可能无法找到控件
            # 尝试使用坐标点击（左侧栏第二个位置通常是通讯录）
            rect = window.rectangle()
            self._notify_progress(f"窗口位置: left={rect.left}, top={rect.top}, right={rect.right}, bottom={rect.bottom}")

            # 微信左侧栏宽度约 60-80 像素
            # 通讯录通常在第二个位置，y 坐标约 150-200
            left_bar_x = rect.left + 40
            contacts_y = rect.top + 180

            self._notify_progress(f"尝试点击通讯录位置: ({left_bar_x}, {contacts_y})")

            # 使用 pywinauto 的鼠标点击
            from pywinauto import mouse
            mouse.click(coords=(left_bar_x, contacts_y))
            time.sleep(self.ACTION_DELAY)

            self._notify_progress("通讯录点击完成")
            return True

        except Exception as e:
            self._notify_progress(f"打开通讯录失败: {e}")
            import traceback
            self._notify_progress(traceback.format_exc())
            return False

    def search_official_account(self, name: str) -> bool:
        """搜索公众号。"""
        self._notify_progress(f"正在搜索公众号: {name}")

        if not self._pywinauto_available:
            return False

        window = self._get_window()
        if not window:
            return False

        try:
            # 确保窗口有焦点
            window.set_focus()
            time.sleep(0.5)

            # 使用键盘快捷键 Ctrl+F 打开搜索
            from pywinauto.keyboard import send_keys
            self._notify_progress("发送 Ctrl+F 打开搜索...")
            send_keys('^f')  # Ctrl+F
            time.sleep(1)

            # 输入公众号名称
            self._notify_progress(f"输入公众号名称: {name}")
            send_keys(name)
            time.sleep(1)

            # 发送回车
            self._notify_progress("发送回车搜索...")
            send_keys('{ENTER}')
            time.sleep(self.ACTION_DELAY * 2)

            self._notify_progress("搜索完成")
            return True

        except Exception as e:
            self._notify_progress(f"搜索失败: {e}")
            import traceback
            self._notify_progress(traceback.format_exc())
            return False

    def click_official_account(self, name: str) -> bool:
        """点击公众号进入详情。"""
        self._notify_progress(f"正在进入公众号: {name}")

        if not self._pywinauto_available:
            return False

        window = self._get_window()
        if not window:
            return False

        try:
            # 使用坐标点击（搜索结果通常在窗口中央）
            rect = window.rectangle()
            center_x = (rect.left + rect.right) // 2
            center_y = (rect.top + rect.bottom) // 2

            self._notify_progress(f"尝试点击搜索结果位置: ({center_x}, {center_y})")

            from pywinauto import mouse
            mouse.click(coords=(center_x, center_y))
            time.sleep(self.ACTION_DELAY)
            return True

        except Exception as e:
            self._notify_progress(f"点击进入失败: {e}")
            return False

    def open_history_articles(self) -> bool:
        """打开历史文章列表。"""
        self._notify_progress("正在打开历史文章...")

        if not self._pywinauto_available:
            return False

        window = self._get_window()
        if not window:
            return False

        try:
            # 使用键盘快捷键打开历史消息
            from pywinauto.keyboard import send_keys
            # 尝试 Alt+H 或其他快捷键
            send_keys('%h')  # Alt+H
            time.sleep(self.ACTION_DELAY * 2)
            return True

        except Exception as e:
            self._notify_progress(f"打开历史文章失败: {e}")
            return False

    def scroll_to_trigger_api(self) -> bool:
        """滚动触发 API 请求。"""
        self._notify_progress("正在滚动触发 API 请求...")

        if not self._pywinauto_available:
            return False

        window = self._get_window()
        if not window:
            return False

        try:
            # 使用鼠标滚轮滚动
            from pywinauto import mouse
            rect = window.rectangle()
            center_x = (rect.left + rect.right) // 2
            center_y = (rect.top + rect.bottom) // 2

            # 向下滚动几次
            for i in range(3):
                mouse.scroll(-3, coords=(center_x, center_y))
                time.sleep(0.5)

            self._notify_progress("滚动完成，等待参数捕获...")
            time.sleep(3)  # 等待 mitmproxy 捕获
            return True

        except Exception as e:
            self._notify_progress(f"滚动失败: {e}")
            return False

    def run_automation(self, account_name: str, max_retries: int = 3) -> AutomationResult:
        """运行完整的自动化流程。

        Args:
            account_name: 公众号名称
            max_retries: 最大重试次数

        Returns:
            AutomationResult 执行结果
        """
        start_time = time.time()
        self._status = AutomationStatus.RUNNING

        for attempt in range(max_retries):
            try:
                self._notify_progress(f"第 {attempt + 1}/{max_retries} 次尝试...")

                # 1. 启动/激活微信
                if not self.is_wechat_running():
                    self.launch_wechat()
                else:
                    self.activate_wechat()

                # 2. 导航到通讯录
                if not self.navigate_to_contacts():
                    raise NavigationError("无法打开通讯录")

                # 3. 搜索公众号
                if not self.search_official_account(account_name):
                    raise NavigationError(f"无法搜索公众号: {account_name}")

                # 4. 点击进入公众号
                if not self.click_official_account(account_name):
                    raise NavigationError(f"无法进入公众号: {account_name}")

                # 5. 打开历史文章
                if not self.open_history_articles():
                    raise NavigationError("无法打开历史文章")

                # 6. 滚动触发 API
                self.scroll_to_trigger_api()

                duration = time.time() - start_time
                self._status = AutomationStatus.SUCCESS

                return AutomationResult(
                    status=AutomationStatus.SUCCESS,
                    message="UI 自动化执行成功，请检查参数是否已更新",
                    duration=duration,
                    retry_count=attempt
                )

            except Exception as e:
                self._notify_progress(f"尝试 {attempt + 1} 失败: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2)
                else:
                    duration = time.time() - start_time
                    self._status = AutomationStatus.FAILED
                    return AutomationResult(
                        status=AutomationStatus.FAILED,
                        message=f"自动化失败: {e}",
                        duration=duration,
                        retry_count=attempt
                    )

        duration = time.time() - start_time
        self._status = AutomationStatus.TIMEOUT
        return AutomationResult(
            status=AutomationStatus.TIMEOUT,
            message="自动化超时",
            duration=duration,
            retry_count=max_retries
        )


def auto_refresh_params(account_name: str, progress_callback: Optional[Callable] = None) -> AutomationResult:
    """自动刷新指定公众号的参数。

    Args:
        account_name: 公众号名称
        progress_callback: 进度回调函数

    Returns:
        AutomationResult 执行结果
    """
    automation = WeChatUIAutomation()

    if progress_callback:
        automation.add_progress_callback(progress_callback)

    return automation.run_automation(account_name)


def create_refresh_notifier() -> Callable[["RefreshResult"], None]:
    """创建刷新结果通知器。"""
    from wechat_fetcher.auto_refresh import RefreshResult

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
    # 命令行运行测试
    import sys

    def print_progress(msg):
        print(f"[自动刷新] {msg}")

    automation = WeChatUIAutomation()
    automation.add_progress_callback(print_progress)

    if len(sys.argv) > 1:
        account = sys.argv[1]
        result = automation.run_automation(account)
        print(f"\n结果: {'成功' if result.status == AutomationStatus.SUCCESS else '失败'}")
        print(f"消息: {result.message}")
    else:
        print("用法: python ui_automation.py <公众号名称>")
