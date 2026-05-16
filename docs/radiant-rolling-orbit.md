# Plan: 微信公众号文章URL抓取工具

## Context

用户需要获取特定微信公众号最近1个月的文章URL列表。根据 `req.md` 描述的技术原理，核心思路是通过MITM代理拦截微信客户端HTTPS流量，提取认证参数（`__biz`, `uin`, `key`），然后用这些参数调用微信文章列表API，按时间过滤后输出文章URL。

## 技术方案

**Python 3.9 + mitmproxy 9.x** — mitmproxy是最成熟的开源MITM代理库，Python生态，天然支持HTTPS解密和addon扩展。

## 项目结构

```
D:\workspace\wechat\
├── requirements.txt           # mitmproxy, requests, click
├── proxy_addon.py             # mitmproxy addon (独立文件, mitmdump -s 加载)
├── wechat_fetcher/
│   ├── __init__.py
│   ├── __main__.py            # python -m wechat_fetcher 入口
│   ├── cli.py                 # CLI (start-proxy / fetch / status 命令)
│   ├── storage.py             # 参数持久化 (params.json)
│   └── fetcher.py             # 微信API客户端 (分页、解析、过滤、限速)
└── params.json                # 提取的认证参数 (gitignore, 敏感信息)
```

## 核心组件

### 1. `proxy_addon.py` — mitmproxy插件
- 拦截所有经过代理的HTTPS请求
- 识别目标为 `mp.weixin.qq.com` 的请求
- 从URL query string / Cookie / Referer中提取 `__biz`, `uin`, `key`
- 提取到完整参数后写入 `params.json`
- mitmproxy会自动生成CA证书，用户需在手机/PC上安装信任

### 2. `wechat_fetcher/storage.py` — 参数存储
- JSON文件存储，按 `__biz` 为key分组
- 记录 `extracted_at` 时间戳（用于判断key是否过期）
- 原子写入（先写临时文件再rename）
- 敏感文件，权限尽量设为 `0o600`

### 3. `wechat_fetcher/fetcher.py` — API客户端
**微信文章列表API：**
```
GET https://mp.weixin.qq.com/mp/profile_ext
  ?action=getmsg
  &__biz={__biz}
  &f=json
  &offset={offset}
  &count=10
  &uin={uin}
  &key={key}
```

**响应解析要点：**
- `general_msg_list` 是双重JSON编码的字符串，需 `json.loads()` 两次
- 只处理 `comm_msg_info.type == 49`（文章类型）
- 多图文推送需展开 `multi_app_msg_item_list`
- `content_url` 可能是相对路径，需拼接完整URL
- `comm_msg_info.datetime` 是Unix时间戳

**分页与过滤：**
- 每页10篇，offset递增10
- 按 `datetime` 倒序排列（最新在前）
- 当页面最旧文章早于30天前 → 截断并停止
- 最多请求100页（安全上限）

**反爬与容错：**
- 每页间隔随机3-6秒延迟
- 限流时指数退避 (60s * 2^n)
- 每页最多重试3次
- 检测 `base_resp.ret` 判断key过期（错误码: -3, -1, 200013, 40001, 40030）

### 4. `wechat_fetcher/cli.py` — CLI

| 命令 | 功能 |
|------|------|
| `start-proxy --port 8080` | 启动mitmdump代理，打印使用说明 |
| `fetch --biz <biz> --days 30` | 加载参数并拉取文章URL |
| `status` | 查看已捕获的公众号参数 |

## 工作流程

```
1. python -m wechat_fetcher start-proxy     → 启动代理
2. 手机配置WiFi代理 + 安装CA证书            → 用户手动操作
3. 微信中打开目标公众号，滑动文章列表        → 触发参数捕获
4. python -m wechat_fetcher fetch --biz xxx  → 拉取文章URL
```

## 依赖安装

```
pip install mitmproxy   # 当前环境已装 requests, click
```

## 实现步骤

1. 创建项目文件结构和 `requirements.txt`
2. 实现 `storage.py` — 参数持久化
3. 实现 `proxy_addon.py` — MITM拦截与参数提取
4. 实现 `fetcher.py` — API调用、解析、分页、过滤
5. 实现 `cli.py` + `__main__.py` — 命令行接口
6. 端到端验证

## 验证方法

1. 启动代理后，用浏览器配置代理访问任意微信公众号文章
2. 检查 `params.json` 是否成功提取参数
3. 运行 `fetch --biz <extracted_biz> --days 30` 验证拉取结果
4. 检查返回的URL列表：标题匹配、日期在30天内、URL可访问

## 安全注意

- `params.json` 包含微信账号会话凭证，已加入 `.gitignore`
- CA证书可解密所有HTTPS流量，使用后建议卸载
- 提取的凭证仅发送至 `mp.weixin.qq.com`（微信官方服务器）
