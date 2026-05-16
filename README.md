# WeChat Fetcher

微信公众号文章抓取工具。通过 MITM 代理拦截微信客户端 HTTPS 流量提取认证参数，进而调用微信文章列表 API 抓取文章 URL，并支持一键下载为 Markdown。

## 功能

- **MITM 代理捕获**：拦截微信流量，自动提取 `__biz`、`uin`、`key` 等认证参数
- **文章列表抓取**：按日期范围或最近 N 天拉取公众号文章 URL
- **文章下载**：将文章正文转换为 Markdown 保存到本地
- **去重索引**：自动跳过已下载文章，避免重复
- **一键工作流**：`fetch` → `dedup` → `download` 一条龙

## 安装

需要 [uv](https://docs.astral.sh/uv/)（Python 包管理器）。

```bash
# 进入项目目录
cd wechat

# 安装依赖并创建虚拟环境
uv sync

# 验证安装
uv run wechat-fetcher --help
```

## 快速开始

### 1. 启动代理

```bash
uv run wechat-fetcher start-proxy
```

### 2. 配置系统代理

将系统代理设为 `127.0.0.1:8080`，安装 mitmproxy CA 证书（浏览器访问 `http://mitm.it`）。

### 3. 捕获参数

在微信桌面版或手机微信中打开目标公众号的"全部消息"页面，向下滑动加载文章。代理终端会输出 `Captured params for __biz=...` 表示成功。

### 4. 一键抓取

```bash
# 对所有已存储账号执行（最近 3 天）
uv run wechat-fetcher run --all --days 3

# 或指定日期范围
uv run wechat-fetcher run --all --from 2026-03-01 --to 2026-03-31
```

输出保存在 `data/articles/` 目录下。

## 常用命令

| 命令 | 用途 |
|------|------|
| `start-proxy` | 启动 MITM 代理，捕获认证参数 |
| `status` | 查看已存储账号和去重索引统计 |
| `fetch --biz <biz> --days 30` | 抓取最近 30 天文章列表 |
| `download --input articles.json` | 下载文章并转 Markdown |
| `run --all --days 3` | 一键工作流（抓取 + 去重 + 下载） |

完整使用说明见 [docs/用户操作手册.md](docs/用户操作手册.md)。

## 技术栈

- Python 3.9+
- [mitmproxy](https://mitmproxy.org/) — MITM 代理
- [Click](https://click.palletsprojects.com/) — CLI 框架
- [BeautifulSoup](https://www.crummy.com/software/BeautifulSoup/) — HTML 解析
- [markdownify](https://github.com/matthewwithanm/python-markdownify) — HTML 转 Markdown

## 项目结构

```
wechat-fetcher/
├── wechat_fetcher/      # 主包
│   ├── cli.py           # CLI 入口
│   ├── fetcher.py       # 微信 API 客户端
│   ├── downloader.py    # 文章下载器
│   ├── dedup.py         # 去重索引
│   ├── storage.py       # 参数持久化
│   ├── proxy_addon.py   # mitmproxy 插件
│   └── workflow.py      # 工作流引擎
├── tests/               # 测试
├── docs/                # 文档
│   ├── exec-plans/      # 执行计划
│   ├── superpowers/     # Claude Code 技能
│   └── 用户操作手册.md
├── pyproject.toml       # 包配置
└── README.md            # 本文件
```

## 安全提醒

- `data/params/` 包含微信账号的接口鉴权参数（`uin` 和 `key`），请勿分享或上传
- mitmproxy 的 CA 证书可以解密 HTTPS 流量，使用完毕后建议卸载
- 本工具利用你自身微信账号的合法权限拉取公开文章信息，请合理使用

## License

[MIT](LICENSE)
