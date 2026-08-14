# 多源并发聚合搜索与网页全文抓取工具 (AI Search & Crawl Tool)

## 1. 工具简介

本工具是为大模型/AI Agent 量身打造的**端到端（End-to-End）信息检索与抓取系统**。

内部采用两阶段（Two-Stage）Pipeline 架构：

1. **多源并发召回（Search）**：并发调度 Bing、百度、头条、B 站、DuckDuckGo 五大搜索引擎，结合「内存 + Redis」双层缓存、语言感知智能分词与广告过滤，去重打分后输出 TopK 结果。
2. **批量并发抓取（Crawl）**：基于「curl_cffi 轻量静态拉取 + 单例无头 Chromium（crawl4ai）兜底」的两级抓取策略，将召回的 TopK 网页并行清洗为高质量 Markdown 文本，供大模型直接作为上下文。

### 核心特性

- 🌐 **五源并发聚合**：Bing / Baidu / Toutiao / DuckDuckGo / BiliBili 异步并发召回，单引擎异常自动容错（10s 超时）；
- 🧠 **语言感知过滤**：基于 jieba 词性标注智能分词，自动区分中文 / 英文 / 中英混合场景，过滤广告与不相关内容；
- ⚡ **双层缓存**：进程内内存缓存 + Redis 缓存，搜索级（TTL 1h）与 URL 内容级（TTL 24h）两级隔离，支持 `--no-cache` 强制实时搜索；
- 🚀 **高性能抓取**：单页优先 curl_cffi 静态拉取（内存占用 < 10MB），失败后回退至全局单例 Chromium；批量场景直接复用单例浏览器 `arun_many` 并发抓取；
- 📦 **结构化输出**：成功时以合法 JSON 输出至 stdout，异常时以 JSON 输出至 stderr 并返回非 0 退出码，便于平台与 Agent 集成。

---

## 2. 目录结构与文件说明

```text
ai_search_tool/
├── main.py                    # CLI 入口（argparse 参数解析 + asyncio Pipeline + JSON stdout/stderr）
├── readme.md                  # 本说明文档
└── web_search/                # 核心业务逻辑包
    ├── __init__.py
    ├── tool_api.py            # 工具 API 编排层（缓存 + 聚合搜索 + 批量抓取的顶层封装）
    ├── config/                # 基础定义与配置
    │   ├── __init__.py
    │   ├── abstract.py        # SearchEngine 抽象基类（统一各搜索引擎接口）
    │   ├── model.py           # SearchResult 数据模型（title/link/snippet/source_engine/is_ad）
    │   └── logging_config.py  # loguru 全局日志配置（控制台 + 文件轮转）
    └── server/                # 服务端核心实现
        ├── __init__.py
        ├── aggregator.py      # 多源并发聚合器（并发召回 / 去重 / 融合打分 / TopN 裁决）
        ├── implement.py       # 五大搜索引擎实现（Bing / Baidu / Toutiao / DuckDuckGo / Bili）
        ├── cache.py           # 内存 + Redis 双层缓存（搜索级缓存 + URL 内容级缓存）
        ├── crawl.py           # 两级抓取模块（curl_cffi 静态 + crawl4ai 单例 Chromium）
        └── filter.py          # 语言感知相关性过滤与广告识别（jieba 词性分词）
```

> 注：仓库根目录未包含 `requirements.txt`，完整依赖清单见下文第 3 节。

---

## 3. 环境依赖与运行说明

- **Python**：3.10+（当前开发环境为 3.13，基于 uv 管理的 `.venv`）；
- **Redis**：默认连接 `localhost:6379`（可在 `web_search/tool_api.py` 的 `SearchCache(...)` 处调整 host/port/password/db）。Redis 不可用时缓存读写会自动降级（仅记录日志），不影响搜索与抓取主流程；
- **第三方依赖**（均来自源码 import）：

| 依赖                      | 用途                                                              |
| ------------------------- | ----------------------------------------------------------------- |
| `redis`                   | 异步 Redis 客户端（缓存层）                                       |
| `curl_cffi`               | 轻量静态抓取 / 搜索引擎请求（chrome120 指纹伪装）                 |
| `crawl4ai`                | 无头 Chromium 网页抓取与 Markdown 转换（含 `arun_many` 批量并发） |
| `beautifulsoup4` + `lxml` | HTML / XML 解析（搜索引擎结果页）                                 |
| `jieba`                   | 中文 / 中英混合智能分词（相关性过滤与融合打分）                   |
| `ddgs`                    | DuckDuckGo 搜索（`ddgs.text`）                                    |
| `bilibili-api-python`     | B 站视频搜索                                                      |
| `loguru`                  | 日志框架（控制台 + 文件）                                         |

安装示例：

```bash
pip install redis curl_cffi crawl4ai beautifulsoup4 lxml jieba ddgs bilibili-api-python loguru
# 首次使用 crawl4ai 需安装浏览器内核（命令视 crawl4ai 版本而定）
crawl4ai-setup   # 或 python -m crawl4ai setup
```

直接运行示例：

```bash
python main.py --query "Python asyncio 异步编程" --topk 3
python main.py --query "LangChain Agent 开发" --mode search --topk 5
python main.py --url https://news.ycombinator.com/ --mode crawl
```

---

## 4. 命令行参数 (CLI Arguments)

| 参数名       | 简写 | 类型     | 默认值     | 说明                                                                                  |
| ------------ | ---- | -------- | ---------- | ------------------------------------------------------------------------------------- |
| `--query`    | `-q` | `string` | `None`     | 搜索关键词（在 `pipeline` 和 `search` 模式下**必填**）                                |
| `--mode`     | `-m` | `string` | `pipeline` | 工作模式：`pipeline`（搜索并自动抓取全文）、`search`（仅搜索）、`crawl`（仅抓取 URL） |
| `--topk`     | `-k` | `int`    | `3`        | 返回的搜索结果数量（默认 3 条）                                                       |
| `--url`      | `-u` | `string` | `None`     | 指定抓取的单个 URL（在 `crawl` 模式下**必填**）                                       |
| `--no-cache` | -    | `flag`   | `False`    | 附加该参数可显式禁用内存 / Redis 缓存，强制实时搜索与抓取                             |

---

## 5. AI 员工调用示例 (ProcessUtil)

### 场景 A：【推荐】搜索并自动抓取网页全文 (Pipeline 模式)

一步到位获取包含标题、链接、摘要以及完整 Markdown 正文的结构化上下文：

```python
ProcessUtil.run_python(
    script="main.py",   # 指向本仓库根目录下的 main.py
    args=["--query", "Python asyncio 异步编程", "--topk", "3"],
    sync=True
)
```

### 场景 B：仅搜索链接与摘要 (Search 模式)

快速获取检索列表，省流量与延迟：

```python
ProcessUtil.run_python(
    script="main.py",
    args=["--query", "LangChain Agent 开发", "--mode", "search", "--topk", "5"],
    sync=True
)
```

### 场景 C：已知目标 URL，精准抓取网页 Markdown 正文 (Crawl 模式)

```python
ProcessUtil.run_python(
    script="main.py",
    args=["--url", "https://news.ycombinator.com/", "--mode", "crawl"],
    sync=True
)
```

---

## 6. 输出 JSON 数据格式说明

标准执行成功时通过 `stdout` 返回合法 JSON 对象，三种模式返回结构如下：

### 6.1 Pipeline 模式返回样例

```json
{
  "status": "success",
  "mode": "pipeline",
  "query": "Python asyncio 异步编程",
  "count": 3,
  "results": [
    {
      "title": "Python Asyncio 异步编程完全指南",
      "link": "https://example.com/asyncio-guide",
      "snippet": "本文详细介绍了 Python 中 asyncio 事件循环与协程的使用...",
      "source_engine": "Bing",
      "markdown_content": "# Python Asyncio 完全指南\n\nAsyncio 是 Python 标准库中用于编写并发代码的库..."
    }
  ],
  "aggregated_markdown": "\n========================================\n\n### [Document 1] URL: https://example.com/asyncio-guide\n\n# Python Asyncio 完全指南..."
}
```

### 6.2 Search 模式返回样例（无 `markdown_content` 与 `aggregated_markdown` 字段）

```json
{
  "status": "success",
  "mode": "search",
  "query": "LangChain Agent 开发",
  "count": 5,
  "results": [
    {
      "title": "LangChain Agents 官方文档",
      "link": "https://example.com/langchain-agents",
      "snippet": "Agent 是 LangChain 中基于 LLM 决策的核心抽象...",
      "source_engine": "Toutiao"
    }
  ]
}
```

### 6.3 Crawl 模式返回样例

```json
{
  "status": "success",
  "mode": "crawl",
  "url": "https://news.ycombinator.com/",
  "markdown_content": "# Hacker News\n\n..."
}
```

> **提示**：大模型（LLM）回答复杂问题时，可优先读取最外层的 `aggregated_markdown` 字段，该字段已按文档序号拼接好标准 Prompt 结构，直接投喂上下文效果最佳。

补充说明：

- `source_engine` 取值为：`Bing` / `Baidu` / `Toutiao` / `DuckDuckGo` / `BiliBili`；
- 抓取失败时 `markdown_content` 为 `"内容抓取失败"`，底层原始失败提示形如 `"web内容获取失败: ..."`。

---

## 7. 异常与错误处理 (Stderr)

如果运行时抛出异常或参数错误，退出码为非 0（`exit status 1`），错误信息将以 JSON 格式输出至 `stderr`：

```json
{
  "status": "error",
  "message": "在 'pipeline' 模式下，必须提供 --query 参数！"
}
```

常见错误信息：

- `在 'pipeline' 模式下，必须提供 --query 参数！`
- `在 'search' 模式下，必须提供 --query 参数！`
- `在 'crawl' 模式下，必须提供 --url 参数！`

---

## 8. 架构与实现要点

### 8.1 两阶段 Pipeline 流程

```text
用户输入 query
   │
   ▼
┌────────────────────────────────────────────────────────────┐
│ 阶段一：聚合搜索 (aggregated_web_search_tool)                │
│  1. 查缓存（内存 → Redis），命中即返回                       │
│  2. 并发调用 5 大搜索引擎（asyncio，10s 超时，异常容错）     │
│  3. 归一化 URL / Title 去重                                 │
│  4. jieba 关键词融合打分，截取 TopK                         │
│  5. 回写内存 + Redis（TTL 1h）                              │
└────────────────────────────────────────────────────────────┘
   │  有效链接列表
   ▼
┌────────────────────────────────────────────────────────────┐
│ 阶段二：批量抓取 (crawl_batch2md_tool)                      │
│  1. Redis MGET 批量查 URL 内容缓存，命中即用                │
│  2. 未命中 → 单例无头 Chromium arun_many 并发抓取           │
│     （单页 crawl2md 会先尝试 curl_cffi 静态拉取兜底）       │
│  3. 回写 Redis（TTL 24h）                                   │
│  4. 内存拼接 aggregated_markdown 大文本（避免二次网络请求）  │
└────────────────────────────────────────────────────────────┘
   │
   ▼
JSON 输出至 stdout
```

### 8.2 缓存机制（search_cache / web_content）

| 维度     | 搜索级缓存                                                                              | URL 内容级缓存                    |
| -------- | --------------------------------------------------------------------------------------- | --------------------------------- |
| Key 生成 | 查询归一化（小写 / 去标点 / 压缩空白）→ MD5 前 16 位 + TopK 向上对齐（1~5→5，6~10→10…） | URL 的 SHA256                     |
| Key 示例 | `search_cache:f0e2a3b1c4d5:5`                                                           | `web_content:<sha256>`            |
| 存储     | 进程内存 + Redis（`setex`）                                                             | Redis（单条 `set` / 批量 `mget`） |
| TTL      | 默认 1 小时                                                                             | 默认 24 小时                      |
| 禁用方式 | CLI 加 `--no-cache`                                                                     | 同左                              |

> 设计说明：查询归一化 + TopK 对齐使「Python 异步编程?」(topk=3) 与 `python   异步编程` (topk=5) 命中同一缓存键，显著提高缓存复用率。

### 8.3 日志

基于 loguru，默认 INFO 级别：

- **控制台**：彩色结构化输出（时间 / 级别 / 模块:行号 / 消息）；
- **文件**：输出至 `web_search/logs/app.log`，单文件超过 10MB 自动轮转，保留 7 天，UTF-8 编码（目录自动创建）。

---

## 9. 免责与注意事项

- 搜索引擎结果页结构可能随站点改版而变化，解析失败时对应引擎会自动降级返回空结果，不影响其他引擎；
- DuckDuckGo 在部分网络环境下可能超时，已内置 5s 超时与异常捕获；
- 批量抓取依赖本机 Chromium 内核（crawl4ai），首次运行请先完成浏览器内核安装。
