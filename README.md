# WeChat Fetcher

![Python](https://img.shields.io/badge/python-%3E%3D3.9-blue)
![License](https://img.shields.io/github/license/HeartFlying/wechat-article-exporter)
![Platform](https://img.shields.io/badge/platform-windows%20%7C%20macOS%20%7C%20linux-lightgrey)

微信公众号文章抓取工具。通过 MITM 代理拦截微信客户端 HTTPS 流量提取认证参数，进而调用微信文章列表 API 抓取文章 URL，并支持一键下载为 Markdown。

## 功能

- **MITM 代理捕获**：拦截微信流量，自动提取 `__biz`、`uin`、`key` 等认证参数
- **文章列表抓取**：按日期范围或最近 N 天拉取公众号文章 URL
- **文章下载**：将文章正文转换为 Markdown 保存到本地
- **去重索引**：自动跳过已下载文章，避免重复
- **一键工作流**：`fetch` → `dedup` → `download` 一条龙
- **按公众号组织**：所有数据按公众号名称分子目录存储，便于管理

## 使用方式

本工具提供四种使用方式，你可以根据需要选择：

| 方式 | 适用场景 | 优点 | 缺点 |
|------|----------|------|------|
| **pip 安装** | 日常使用 | 简单方便，自动更新 | 需要 Python 环境 |
| **uv 管理** | 现代 Python 项目管理 | 极速依赖安装，环境隔离 | 需要安装 uv |
| **源代码运行** | 开发调试 | 可修改代码，实时生效 | 需要配置开发环境 |
| **可执行文件** | 无 Python 环境 | 无需安装，开箱即用 | 文件较大，启动稍慢 |

---

## 方式一：pip 安装（推荐）

### 安装

```bash
pip install wechat-fetcher
```

### 验证安装

```bash
wechat-fetcher --help
```

### 使用

```bash
# 启动代理捕获参数
wechat-fetcher start-proxy

# 查看状态
wechat-fetcher status

# 一键抓取
wechat-fetcher run --all --days 3
```

---

## 方式二：uv 管理（推荐）

[uv](https://docs.astral.sh/uv/) 是一个极速的 Python 包管理器和环境管理工具，相比 pip 具有更快的依赖解析和安装速度。

### 安装 uv

```bash
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 克隆仓库

```bash
git clone https://github.com/HeartFlying/wechat-article-exporter.git
cd wechat-article-exporter
```

### 创建虚拟环境并安装依赖

```bash
# 创建虚拟环境（使用项目指定的 Python 版本）
uv venv

# 激活虚拟环境
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

# 安装项目依赖
uv pip install -e .

# 开发模式安装（包含开发依赖）
uv pip install -e ".[dev]"
```

### 使用 uv 运行

```bash
# 直接运行（无需显式激活虚拟环境）
uv run python -m wechat_fetcher --help

# 运行具体命令
uv run python -m wechat_fetcher start-proxy
uv run python -m wechat_fetcher status
uv run python -m wechat_fetcher run --all --days 3
```

### 开发调试

```bash
# 运行测试
uv run pytest

# 代码检查
uv run ruff check .
uv run mypy wechat_fetcher
```

### uv 与 pip 对比优势

| 特性 | uv | pip |
|------|-----|-----|
| 依赖解析速度 | ⚡ 极速 | 🐢 较慢 |
| 虚拟环境管理 | ✅ 内置支持 | ❌ 需配合 venv |
| 锁文件支持 | ✅ 原生支持 | ❌ 需配合 pip-tools |
| 全局工具安装 | ✅ `uv tool` | ❌ 需配合 pipx |

---

## 方式三：源代码运行

### 环境要求

- Python 3.9+
- pip 包管理器

### 克隆仓库

```bash
git clone https://github.com/HeartFlying/wechat-article-exporter.git
cd wechat-article-exporter
```

### 创建虚拟环境（推荐）

```bash
# Windows
python -m venv venv
venv\Scripts\activate

# macOS/Linux
python -m venv venv
source venv/bin/activate
```

### 安装依赖

```bash
pip install -e .
```

### 开发模式安装（可修改代码）

```bash
pip install -e ".[dev]"
```

### 源代码运行

```bash
# 方式1：作为模块运行
python -m wechat_fetcher --help

# 方式2：直接运行入口文件
python wechat_fetcher/__main__.py --help

# 方式3：使用包内命令（安装后）
wechat-fetcher --help
```

### 开发调试

```bash
# 运行测试
pytest

# 代码检查
ruff check .
mypy wechat_fetcher
```

---

## 方式四：打包为可执行文件

适用于没有 Python 环境的用户，或需要分发给他人使用。

### 打包准备

确保已安装开发依赖：

**使用 pip：**
```bash
pip install -e ".[dev]"
```

**使用 uv：**
```bash
uv pip install -e ".[dev]"
```

### 执行打包

```bash
# 方式1：打包为目录（推荐，启动快，文件较小）
python build_exe.py

# 方式2：打包为单文件（启动慢，文件大，但只有一个文件）
python build_exe.py --onefile
```

### 打包输出

打包完成后，输出位于 `dist/` 目录：

```
dist/
├── wechat-fetcher/              # 目录模式输出
│   ├── wechat-fetcher.exe       # 主程序
│   ├── _internal/               # 依赖文件
│   └── ...
└── wechat-fetcher.exe           # 单文件模式输出
```

### 分发使用

**目录模式**：
1. 将整个 `dist/wechat-fetcher` 目录压缩
2. 分发给用户
3. 用户解压后直接运行 `wechat-fetcher.exe`

**单文件模式**：
1. 直接分发 `dist/wechat-fetcher.exe`
2. 用户双击即可运行

---

## 快速开始

无论使用哪种方式，基本使用流程相同：

### 1. 启动代理

```bash
wechat-fetcher start-proxy
```

手机或电脑配置代理后，打开微信浏览公众号文章列表，工具会自动捕获认证参数。

### 2. 查看状态

```bash
wechat-fetcher status
```

### 3. 一键抓取

```bash
# 对所有已存储账号执行（最近 3 天）
wechat-fetcher run --all --days 3

# 或指定日期范围
wechat-fetcher run --all --from 2026-03-01 --to 2026-03-31
```

---

## 详细使用指南

### 手机代理模式

```bash
# 显示本机 IP，方便手机配置代理
wechat-fetcher start-proxy --show-ip
```

1. 手机和电脑连接同一 Wi-Fi
2. 手机 Wi-Fi 设置中配置代理：服务器填电脑 IP，端口填 8080
3. 手机浏览器访问 http://mitm.it 安装 CA 证书
4. 打开微信，浏览目标公众号的历史文章
5. 观察命令行窗口出现 "Captured params" 即表示成功

### 桌面代理模式

```bash
wechat-fetcher start-proxy
```

1. Windows 设置系统代理：地址 127.0.0.1，端口 8080
2. 浏览器访问 http://mitm.it 下载并安装 Windows 证书
3. 完全退出并重新打开微信桌面版
4. 打开目标公众号，点击"全部消息"并下滑加载

### 常用命令

| 命令 | 用途 |
|------|------|
| `wechat-fetcher info` | 显示工具信息和数据目录位置 |
| `wechat-fetcher start-proxy` | 启动 MITM 代理，捕获认证参数 |
| `wechat-fetcher status` | 查看已存储账号和去重索引统计 |
| `wechat-fetcher fetch --biz <biz> --days 30` | 抓取最近 30 天文章列表 |
| `wechat-fetcher download --input articles.json` | 下载文章并转 Markdown |
| `wechat-fetcher run --all --days 3` | 一键工作流（抓取 + 去重 + 下载） |
| `wechat-fetcher clear --name <公众号名称>` | 清除指定公众号的所有数据 |

---

## 数据目录结构

默认数据存储在用户主目录下：

- **Windows**: `C:\Users\<用户名>\.wechat-fetcher\data\`
- **macOS**: `~/.wechat-fetcher/data/`
- **Linux**: `~/.wechat-fetcher/data/`

### 目录组织

```
~/.wechat-fetcher/data/
├── accounts/                          # 所有公众号数据按子目录组织
│   ├── 示例公众号名称/                 # 公众号名称（安全化后的文件夹名）
│   │   ├── params.json                # 该公众号的认证参数
│   │   ├── dedup_index.json           # 该公众号的去重索引
│   │   └── articles/                  # 该公众号的文章
│   │       ├── 2024-01-15_文章标题1/
│   │       │   └── content.md
│   │       └── ...
│   └── 另一个公众号/
│       ├── params.json
│       ├── dedup_index.json
│       └── articles/
│           └── ...
└── ...
```

### 自定义数据目录

可以通过环境变量自定义：

```bash
# 自定义数据目录
export WECHAT_FETCHER_DATA=/path/to/data

# 自定义配置目录
export WECHAT_FETCHER_CONFIG=/path/to/config
```

Windows 系统使用：
```cmd
set WECHAT_FETCHER_DATA=D:\wechat-data
```

---

## 命令参考

```
Usage: wechat-fetcher [OPTIONS] COMMAND [ARGS]...

  微信公众号文章抓取工具

Options:
  --version   Show the version and exit.
  --help      Show this message and exit.

Commands:
  clear        清除存储的参数
  download     下载文章并转换为 Markdown
  fetch        从微信公众号抓取文章 URL 列表
  info         显示工具信息和数据目录位置
  run          一键工作流: 抓取 → 去重 → 下载
  start-proxy  启动 MITM 代理
  status       查看已存储的账号参数和去重索引
```

---

## 技术栈

- Python 3.9+
- [mitmproxy](https://mitmproxy.org/) — MITM 代理
- [Click](https://click.palletsprojects.com/) — CLI 框架
- [BeautifulSoup](https://www.crummy.com/software/BeautifulSoup/) — HTML 解析
- [markdownify](https://github.com/matthewwithanm/python-markdownify) — HTML 转 Markdown
- [PyInstaller](https://pyinstaller.org/) — 打包可执行文件

---

## 项目结构

```
wechat-article-exporter/
├── wechat_fetcher/          # 主包
│   ├── __init__.py          # 包初始化
│   ├── __main__.py          # 模块入口
│   ├── cli.py               # CLI 入口
│   ├── config.py            # 配置管理
│   ├── fetcher.py           # 微信 API 客户端
│   ├── downloader.py        # 文章下载器
│   ├── dedup.py             # 去重索引
│   ├── storage.py           # 参数持久化
│   ├── proxy_addon.py       # mitmproxy 插件
│   └── workflow.py          # 工作流引擎
├── tests/                   # 测试
├── build_exe.py             # 打包脚本
├── pyproject.toml           # 包配置
└── README.md                # 本文件
```

---

## 开发

```bash
# 克隆仓库
git clone https://github.com/HeartFlying/wechat-article-exporter.git
cd wechat-article-exporter

# 方式1：使用 uv（推荐）
uv venv
uv pip install -e ".[dev]"
uv run pytest
uv run ruff check .

# 方式2：使用 pip
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -e ".[dev]"
pytest
ruff check .
mypy wechat_fetcher
```

---

## 安全提醒

- `~/.wechat-fetcher/data/accounts/` 包含微信账号的接口鉴权参数（`uin` 和 `key`），请勿分享或上传
- mitmproxy 的 CA 证书可以解密 HTTPS 流量，使用完毕后建议卸载
- 本工具利用你自身微信账号的合法权限拉取公开文章信息，请合理使用

---

## License

[MIT](LICENSE)
