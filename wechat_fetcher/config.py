"""配置管理：支持用户目录和数据目录配置。"""

import os
from pathlib import Path
from typing import Optional


class Config:
    """管理应用配置和数据目录。"""

    APP_NAME = "wechat-fetcher"

    def __init__(self):
        self._data_dir: Optional[Path] = None
        self._config_dir: Optional[Path] = None

    @property
    def data_dir(self) -> Path:
        """获取数据目录（用户主目录下）。"""
        if self._data_dir is None:
            # 优先使用环境变量，否则使用用户主目录
            if os.environ.get("WECHAT_FETCHER_DATA"):
                self._data_dir = Path(os.environ["WECHAT_FETCHER_DATA"])
            else:
                home = Path.home()
                self._data_dir = home / ".wechat-fetcher" / "data"
            self._data_dir.mkdir(parents=True, exist_ok=True)
        return self._data_dir

    @property
    def config_dir(self) -> Path:
        """获取配置目录。"""
        if self._config_dir is None:
            if os.environ.get("WECHAT_FETCHER_CONFIG"):
                self._config_dir = Path(os.environ["WECHAT_FETCHER_CONFIG"])
            else:
                home = Path.home()
                self._config_dir = home / ".wechat-fetcher" / "config"
            self._config_dir.mkdir(parents=True, exist_ok=True)
        return self._config_dir

    @property
    def params_dir(self) -> Path:
        """获取参数存储目录。"""
        path = self.data_dir / "params"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def articles_dir(self) -> Path:
        """获取文章下载目录。"""
        path = self.data_dir / "articles"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def index_dir(self) -> Path:
        """获取索引目录。"""
        path = self.data_dir / "index"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def config_file(self) -> Path:
        """获取配置文件路径。"""
        return self.config_dir / "config.json"


# 全局配置实例
_config: Optional[Config] = None


def get_config() -> Config:
    """获取全局配置实例。"""
    global _config
    if _config is None:
        _config = Config()
    return _config
