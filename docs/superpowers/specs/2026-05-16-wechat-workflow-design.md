# 微信公众号文章自动抓取工作流设计

## 目标

将现有分步执行的微信文章抓取工具打包为一键式工作流，支持多公众号、日期范围查询、标题+URL双重去重、自动下载保存，最大化减少人工介入。

## 架构

```
CLI 层 (cli.py)
├── start-proxy   # 不变 — 启动 MITM 代理截获认证参数
├── fetch         # 扩展 — 增加 --from/--to 日期范围
├── download      # 不变
├── status        # 扩展 — 显示去重索引状态
└── run           # 新增 — 一键工作流（编排引擎入口）

核心层
├── workflow.py   # 新增 — WorkflowEngine：抓取→去重→下载编排
├── fetcher.py    # 扩展 — fetch_articles() 支持 from_date/to_date
├── downloader.py # 轻改 — download_all() 接受可选 dedup 实例
├── dedup.py      # 新增 — DedupIndex：标题+URL 去重索引
└── storage.py    # 扩展 — 参数路径从 ~/.wechat_fetcher 迁至 data/params/
```

## 数据目录

项目完全自包含，所有运行时数据存放在 `data/` 下：

```
wechat/
├── wechat_fetcher/       # 包源码
│   ├── cli.py
│   ├── fetcher.py
│   ├── downloader.py
│   ├── storage.py
│   ├── dedup.py          # 新增
│   └── workflow.py       # 新增
├── data/                 # 运行时数据根目录（.gitignore）
│   ├── params/           # 认证参数，按 biz 拆分为独立 JSON
│   │   └── <biz>.json
│   ├── index/            # 去重索引
│   │   └── dedup_index.json
│   └── articles/         # 已下载文章
│       └── <date>_<title>/
│           └── content.md
├── docs/
├── proxy_addon.py
├── pyproject.toml
└── CLAUDE.md
```

数据迁移对照：

| 数据 | 原路径 | 新路径 |
|------|--------|--------|
| 认证参数 | `~/.wechat_fetcher/params.json` | `data/params/<biz>.json` |
| 去重索引 | 无 | `data/index/dedup_index.json` |
| 下载文章 | `./articles/` | `data/articles/` |

## 组件设计

### dedup.py — 去重索引

独立模块，维护 `data/index/dedup_index.json`，按 biz 分组存储已下载文章记录。

```
DedupIndex(root_dir="data/")
├── is_duplicate(biz, title, url) → bool   # 标题或URL任一命中判重
├── mark_seen(biz, title, url)             # 下载成功后登记
├── stats(biz=None) → dict                 # 总量/按biz/最后更新时间
└── _index_path → data/index/dedup_index.json
```

索引 JSON 结构：

```json
{
  "<biz>": {
    "titles": {"文章标题1": "2026-05-15T10:00:00", "文章标题2": "..."},
    "urls": {"https://...": "2026-05-15T10:00:00"}
  }
}
```

判重逻辑：标题精确匹配 OR URL 精确匹配，任一命中返回 True。跨 biz 不互斥。

### workflow.py — 编排引擎

```
WorkflowEngine(root_dir="data/")
├── run(biz, from_date, to_date, days, output_dir, wait_proxy)
│   ├── 1. 检查/等待认证参数
│   │     --wait-proxy 时轮询 ParamStore（3s 间隔，最长 5 分钟）
│   │     参数就绪后自动继续
│   ├── 2. 调用 Fetcher.fetch_articles() 拉取列表
│   ├── 3. 逐篇过 Dedup.is_duplicate() 过滤重复
│   ├── 4. 调用 Downloader 下载新文章
│   └── 5. 下载成功的逐篇登记 Dedup.mark_seen()
└── run_all(biz_list, ...)  # 对多个公众号依次执行
```

两种使用场景：

```
# 日常更新（参数有效期内）
$ wechat-fetcher run --all --days 3

# 参数过期后刷新并自动继续
$ wechat-fetcher run --all --days 3 --wait-proxy
→ 启动代理 → 用户打开微信刷一遍公众号 → 自动检测参数 → 自动开始抓取下载
```

### 现有模块扩展

**fetcher.py**：
- `fetch_articles()` 新增 `from_date`/`to_date` 参数（datetime.date），内部转时间戳
- `--days` 与 `--from/--to` 互斥，CliRunner 层校验

**downloader.py**：
- `download_all()` 新增可选参数 `dedup: DedupIndex`
- 下载前二次校验去重，防止 CLI 直调 `download` 时重复

**storage.py**：
- `ParamStore` 默认路径调整为 `data/params/`
- 参数存储从单文件聚合改为按 biz 拆分文件
- 保持 `save()/load()/list_accounts()/delete()` 接口不变

## 错误处理

### 参数就绪前

| 场景 | 行为 |
|------|------|
| `--wait-proxy` 超时（5 分钟） | 退出，提示用户打开微信刷目标公众号后重试 |
| biz 无参数且非 `--wait-proxy` | 立即退出，列出已存储的账号供参考 |

### 抓取阶段

| 场景 | 行为 |
|------|------|
| KeyExpired | 跳过该 biz，标记"需刷新参数"，继续下一个 biz |
| 网络超时 / 429 限流 | 指数退避重试（现有逻辑），3 次失败后跳过该 biz |
| API 返回空列表 | 正常结束，输出"0 篇新文章" |

### 下载阶段

| 场景 | 行为 |
|------|------|
| 单篇下载失败 | 记录到失败列表，继续下一篇，不登记去重 |
| 单篇保存失败 | 同上 |
| HTML 解析失败 | 保存原始 HTML 到 `<title>/raw.html`，Markdown 内容标记警告 |

### 整体退出码

- exit 0：全部成功
- exit 1：全部失败
- exit 2：部分失败（stderr 输出失败摘要）

核心原则：**部分失败不中断整体**，每 biz 和每篇文章独立处理。

## 测试策略

| 层级 | 内容 | 方式 |
|------|------|------|
| 去重索引 | DedupIndex 增删查、跨 biz 隔离、持久化恢复 | pytest 单元测试，无网络依赖 |
| 日期解析 | --from/--to/--days 互斥校验 | click CliRunner 测试 |
| 工作流编排 | run() 各分支（无参/过期/正常/部分失败） | mock fetcher + downloader，验证调用顺序和去重登记 |
| 端到端 | 完整 run --all 流程 | 仅在有真实有效参数时手动验证，不入 CI |

## 自动化的硬边界

微信 API 的 `key` 参数时效短（通常数小时），必须在微信客户端实际打开目标公众号时由客户端生成，无长期有效 Token。因此：

- **无法完全消除人工**：首次抓取或参数过期后，需要人在微信里打开目标公众号并浏览历史文章
- **可最大化自动化**：参数有效期内全自动；`--wait-proxy` 模式代理就绪后即刻自动继续
- **多公众号**：代理运行期间依次打开每个目标公众号，参数全部存下后自动批量处理
