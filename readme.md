# AI Search & Crawl Tool — 多源并发聚合搜索与网页全文抓取工具

## 1. 工具简介

本工具是专为大模型与 AI Agent 量身打造的**高性能、低内存占用端到端（End-to-End）信息检索与正文提取系统**。针对低配环境进行了深度工程优化，零深度学习重型依赖即可实现高质量检索与精准 Token 压缩。

系统采用两阶段（Two-Stage）Pipeline 架构：

| 阶段 | 功能 | 核心技术 |
|------|------|---------|
| **Search** | 八源并发召回与 BM25 竞速重排 | First-N 熔断 + 轻量级 BM25 算法 + 双层缓存 |
| **Crawl** | 批量并发抓取与 Token 压缩 | `webclaw` CLI（可选增强）/ `httpx` 静态拉取兜底 + 滑动窗口切块 |

### 核心特性

- 🌐 **八源并发与竞速熔断**：Bing / Baidu / Toutiao / DuckDuckGo / BiliBili / Tavily / Douyin / GitHub 并发召回；首批累积返回达到 `topk * 2` 即自动触发竞速熔断并取消慢速任务。
- 🎯 **轻量级 BM25 重排**：纯 CPU 毫秒级计算，零模型内存开销，结合 IDF 与标题强匹配对多源结果精准打分。
- 🧠 **语言感知过滤**：基于 jieba 词性标注智能分词，自动适配中文 / 英文 / 中英混合场景，彻底拦截广告与噪声。
- ⚡ **超高速双层缓存**：进程内内存缓存 + 异步 Redis 缓存，结合 `orjson` 极速二进制序列化与 TopK 向上对齐机制。
- ✂️ **Token 智能压缩**：优先使用 `webclaw -f llm` 格式（可选依赖，见第 3 节）以获得更高压缩率；未安装时自动降级至 `httpx` 静态拉取 + `html2text` 解析，长文本仍会执行滑动窗口切块，复用 BM25 挑选 Top 2 个相关 Chunk 组装 Context。
- 🛡️ **弱依赖容灾**：`webclaw` 为可选增强依赖——未在 `PATH` 中或未安装时，系统自动降级使用纯 Python 实现（`httpx` + `html2text`），功能不缺失，仅 Token 压缩比略低于 `webclaw -f llm` 模式。静态抓取支持 SSL 报错自动降级重试与 Content-Type 防护。
- 📱 **视频内容支持**：Douyin 引擎额外携带 `video_url` 字段，便于后续视频内容处理。
- 💻 **开源仓库搜索**：GitHub 引擎通过官方 REST API 搜索仓库，自动清洗 Query 并支持多词降级重试，返回含 Stars / Language 元信息。

---

## 2. 目录结构

```text
ai_search_tool/
├── main.py                    # CLI 入口（argparse + asyncio Pipeline + orjson I/O）
├── readme.md                  # 本说明文档
└── web_search/                # 核心业务逻辑包
    ├── __init__.py
    ├── tool_api.py            # 工具 API 编排层（缓存 + 竞速搜索 + Token 压缩抓取的顶层封装）
    ├── config/                # 基础定义与配置
    │   ├── __init__.py
    │   ├── abstract.py        # SearchEngine 抽象基类（统一搜索引擎规范）
    │   ├── model.py           # SearchResult 数据模型（title/link/snippet/source_engine/video_url/is_ad）
    │   └── logging_config.py  # loguru 全局日志配置（异步控制台 + 文件轮转）
    └── server/                # 服务端核心实现
        ├── __init__.py
        ├── aggregator.py      # 竞速聚合器与全局单例 BM25Ranker（First-N 熔断 / 去重 / BM25 重排）
        ├── implement.py       # 八大搜索引擎实现（Bing / Baidu / Toutiao / DuckDuckGo / Bili / Tavily / Douyin / GitHub）
        ├── cache.py           # 内存 + Redis 双层缓存（基于 orjson 高性能序列化）
        ├── crawl.py           # webclaw 子进程抓取（可选）+ httpx 静态降级 + 滑动窗口切块算法
        └── filter.py          # 语言感知相关性过滤与广告识别（jieba 词性分词）
```

---

## 3. 环境依赖与运行说明

### 前置要求

- **Python**：3.10+（推荐基于 `uv` 或 `venv` 管理依赖环境）
- **Redis**：默认连接 `localhost:6379`（可在 `tool_api.py` 调整）。Redis 异常时自动降级为纯内存缓存，不阻断主流程
- **webclaw CLI（可选增强）**：若已安装并加入 `PATH`，系统将优先调用 `webclaw` 执行高压缩率抓取（`-f llm` 模式，约 90% Token 压缩）；未安装时自动降级至 `httpx` 静态拉取 + `html2text` 解析，搜索与抓取功能完整可用

### Python 依赖

```bash
pip install redis orjson curl_cffi httpx html2text beautifulsoup4 lxml jieba ddgs bilibili-api-python loguru
```

### 环境变量

| 变量名 | 说明 |
|--------|------|
| `DOUYIN_FALLBACK_COOKIE` | 抖音搜索引擎的登录 Cookie，可作为全局 fallback 凭证 |

---

## 4. 命令行参数 (CLI Arguments)

| 参数名 | 简写 | 类型 | 默认值 | 说明 |
|--------|------|------|--------|------|
| `--query` | `-q` | `string` | `None` | 搜索关键词（`pipeline` / `search` 模式必填） |
| `--mode` | `-m` | `string` | `pipeline` | 工作模式：`pipeline`（搜索+重排+抓取+压缩）、`search`（仅搜索）、`crawl`（仅抓取 URL） |
| `--topk` | `-k` | `int` | `3` | 返回搜索结果数量（默认 3 条） |
| `--url` | `-u` | `string` | `None` | 指定抓取的单个 URL（`crawl` 模式必填） |
| `--no-cache` | — | `flag` | `False` | 禁用内存 / Redis 缓存，强制发起实时网络请求 |
| `--no-compress` | — | `flag` | `False` | 禁用正文滑动切块与 Token 压缩，返回完整正文 |
| `--douyin-cookie` | — | `string` | `None` | 自定义抖音登录 Cookie 凭证（不传则读取环境变量 `DOUYIN_FALLBACK_COOKIE`） |

### 运行示例

```bash
# 完整 Pipeline：搜索 + BM25 重排 + 抓取 + Token 滑动切块压缩
python main.py --query "Python asyncio 异步编程最佳实践" --topk 3

# 纯搜索模式：快速获取重排后的摘要与链接
python main.py --query "LangChain Agent 开发" --mode search --topk 5

# 纯抓取模式：抓取单个网页正文
python main.py --url https://news.ycombinator.com/ --mode crawl

# 禁用缓存与 Token 压缩（返回完整正文）
python main.py --query "Rust 异步并发" --no-cache --no-compress
```

---

## 5. AI Agent / 平台调用示例

### 场景 A：搜索并自动抓取网页全文（Pipeline 模式）

获取经 BM25 筛选与 Token 压缩的高价值上下文：

```python
ProcessUtil.run_python(
    script="main.py",
    args=["--query", "Python asyncio 异步编程", "--topk", "3"],
    sync=True
)
```

### 场景 B：仅搜索链接与生成 LLM 简报（Search 模式）

```python
ProcessUtil.run_python(
    script="main.py",
    args=["--query", "LangChain Agent 开发", "--mode", "search", "--topk", "5"],
    sync=True
)
```

### 场景 C：已知目标 URL，抓取网页 Markdown 正文（Crawl 模式）

```python
ProcessUtil.run_python(
    script="main.py",
    args=["--url", "https://python.org", "--mode", "crawl"],
    sync=True
)
```

---

## 6. 输出 JSON 数据格式说明

工具成功执行时通过 `stdout` 输出标准 JSON 字符串：

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
      "source_engine": "Tavily",
      "markdown_content": "# Python Asyncio 完全指南\n\nAsyncio 是 Python 用于编写并发代码的库..."
    }
  ],
  "llm_search_summary": "[1] Python Asyncio 异步编程完全指南\n    URL: https://example.com/asyncio-guide (Source: Tavily)\n    Snippet: 本文详细介绍了 Python 中 asyncio 事件循环与协程的使用...",
  "aggregated_markdown": "\n========================================\n\n### [Document 1] URL: https://example.com/asyncio-guide\n\n# Python Asyncio 完全指南\n\n..."
}
```

### 6.2 Search 模式返回样例

```json
{
  "status": "success",
  "mode": "search",
  "query": "LangChain Agent 开发",
  "count": 5,
  "results": [
    {
      "title": "LangChain Agents 官方指南",
      "link": "https://example.com/langchain-agents",
      "snippet": "Agent 核心在于大语言模型决策...",
      "source_engine": "Bing"
    }
  ],
  "llm_search_summary": "[1] LangChain Agents 官方指南\n    URL: https://example.com/langchain-agents (Source: Bing)\n    Snippet: Agent 核心在于大语言模型决策..."
}
```

### 6.3 Crawl 模式返回样例

```json
{
  "status": "success",
  "mode": "crawl",
  "url": "https://news.ycombinator.com/",
  "markdown_content": "# Hacker News\n\n1. Show HN: Webclaw Fast Crawler..."
}
```

> **LLM 消费建议**：大模型回答问题时，可直接读取 `aggregated_markdown` 作为 Prompt 上下文；若仅需搜索结果概览，直接读取 `llm_search_summary`。

---

## 7. 异常与错误处理

运行时异常或参数错误将返回退出码 `1`，错误信息以 JSON 格式输出至 `stderr`：

```json
{
  "status": "error",
  "message": "在 'pipeline' 模式下，必须提供 --query 参数！"
}
```

---

## 8. 架构与优化机制详解

### 8.1 完整执行流水线

```text
用户输入 query
   │
   ▼
┌─────────────────────────────────────────────────────────────┐
│ 阶段一：竞速聚合搜索 (aggregated_web_search_tool)            │
│  1. 查缓存（内存 → Redis orjson 极速反序列化）               │
│  2. 并发请求 8 大引擎（Bing/Baidu/Toutiao/DDG/Bili/Tavily/抖音/GitHub）│
│  3. First-N 竞速熔断：结果达标立即 cancel 慢引擎任务          │
│  4. URL 规范化与标题全局去重                                │
│  5. 全局单例 BM25Ranker 语义相关性打分重排                   │
│  6. 回写内存 + Redis（TTL 1h）                              │
└─────────────────────────────────────────────────────────────┘
   │  有效链接列表
   ▼
┌─────────────────────────────────────────────────────────────┐
│ 阶段二：抓取与 Token 压缩 (crawl_batch2md_tool)             │
│  1. Redis MGET 批量查 URL 内容缓存                          │
│  2. 未命中 → 优先调起 webclaw CLI 批量抓取（-f llm，可选）  │
│     ↓ 若 webclaw 不可用则自动降级                           │
│     → httpx 静态拉取 + html2text 解析                       │
│  3. 回写 Redis（TTL 24h）                                    │
│  4. 滑动窗口切块（Chunking）+ BM25 提取 Top 2 个相关段落    │
│  5. 组装 aggregated_markdown 投喂大模型                      │
└─────────────────────────────────────────────────────────────┘
   │
   ▼
orjson 快速输出 JSON 到 stdout
```

### 8.2 缓存设计

| 维度 | 搜索级缓存 (`search_cache`) | URL 内容级缓存 (`web_content`) |
|------|---------------------------|-------------------------------|
| **Key 生成** | Query 归一化（转小写/去标点/合并空白）→ MD5 前 16 位 + TopK 向上对齐（5/10/20） | URL 的 SHA256 哈希 |
| **存储介质** | 本地字典内存 + Redis（`orjson` 序列化） | Redis（单条 `set` / 批量 `mget`） |
| **过期时间** | 默认 1 小时 | 默认 24 小时 |

---

## 9. 注意事项

- **webclaw 为可选依赖**：若已安装并位于 `PATH`，将获得更好的 Token 压缩率；未安装时系统完全正常运作，仅抓取质量略低（使用 `httpx` + `html2text` 替代）。
- **网络波动**：DuckDuckGo 与海外站点在部分网络环境下可能存在连通性问题，系统已内置 First-N 竞速熔断与全局超时防护，不会拖慢整体响应。
- **抖音引擎**：需维护有效的 Cookie（见 `DouyinEngine.__init__`），Cookie 失效时将返回空结果。可通过 `--douyin-cookie` 参数传递，或设置环境变量 `DOUYIN_FALLBACK_COOKIE` 作为全局 fallback 凭证。
- **GitHub 引擎**：使用 GitHub 官方 REST API，存在每 IP 每小时 60 次的速率限制（403 时自动降级为空结果）。Query 中的 `github.com` / `github` 等冗余词会自动剔除。支持 SSL 容错与多词降级重试。
- **Tavily / GitHub 凭证**：通过 `UserCredentials` 对象传入（`tool_api.py`），支持 `tavily_api_key` 与 `github_token`。
- **日志位置**：默认输出至 `<project>/logs/app.log`，按 10MB 自动切分，保留 7 天。

---

## 10. 扩展指南

本项目采用抽象基类 `SearchEngine`（定义于 `config/abstract.py`），可快速接入新的搜索引擎。只需实现以下方法即可：

```python
from web_search.config.abstract import SearchEngine
from web_search.config.model import SearchResult, UserCredentials

class MyEngine(SearchEngine):
    async def search(self, query: str, topk: int, credentials: Optional[UserCredentials] = None) -> List[SearchResult]:
        # 实现搜索逻辑，返回 SearchResult 列表
        ...
```

然后将其加入 `tool_api.py` 的 `DEFAULT_ENGINES` 列表即可生效。

---

*作者：Huijian Qin · 版本：v1.0.4 · 更新日期：2026-08-20*
