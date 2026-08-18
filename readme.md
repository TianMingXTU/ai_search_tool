# 多源并发聚合搜索与网页全文抓取工具 (AI Search & Crawl Tool)

## 1. 工具简介

本工具是专为大模型与 AI Agent 量身打造的**高性能、低内存占用端到端（End-to-End）信息检索与正文提取系统**。针对 2核4GB 等低配环境进行了深度工程优化，零深度学习重型依赖即可实现高质量检索与精准 Token 压缩。

系统采用两阶段（Two-Stage）Pipeline 架构：

1. **六源并发召回与 BM25 竞速重排（Search）**：并发调度 Bing、百度、头条、B 站、DuckDuckGo 及 Tavily 六大搜索引擎，采用 **First-N 竞速熔断** 剔除长尾延迟，结合轻量级 **BM25 算法** 与「内存 + Redis」双层缓存输出高相关 TopK 结果。
2. **批量并发抓取与 Token 压缩（Crawl）**：基于 `webclaw` CLI（`-f llm` 原生压缩约 90% 标记）进行多进程/批量抓取，并辅以带 SSL 容错与 `html2text` 的静态拉取兜底；引入**滑动窗口切块（Chunking）与全局 BM25 语义检索**，仅提取与 Query 最匹配的核心段落。

### 核心特性

- 🌐 **六源并发与竞速熔断**：Bing / Baidu / Toutiao / DuckDuckGo / BiliBili / Tavily 并发召回；首批累积返回达到 `topk * 2` 即自动触发竞速熔断并取消慢速任务。
- 🎯 **轻量级 BM25 重排**：纯 CPU 毫秒级计算，零模型内存开销，结合 IDF 与标题强匹配对多源结果精准打分。
- 🧠 **语言感知过滤**：基于 jieba 词性标注智能分词，自动适配中文 / 英文 / 中英混合场景，彻底拦截广告与噪声。
- ⚡ **超高速双层缓存**：进程内内存缓存 + 异步 Redis 缓存，结合 `orjson` 极速二进制序列化与 TopK 向上对齐机制。
- ✂️ **Token 智能压缩**：默认采用 `webclaw -f llm` 格式；长文本自动执行滑动窗口切块，复用 BM25 挑选 Top 2~3 个相关 Chunk 组装 Context，大幅节省 LLM 上下文与推理开销。
- 🛡️ **低配环境友好与容灾**：彻底移除 `crawl4ai` 重型依赖，降低内存占用；静态抓取支持 SSL 报错自动降级重试与 Content-Type 防护。

---

## 2. 目录结构与文件说明

```text
ai_search_tool/
├── main.py                    # CLI 入口（argparse 参数解析 + asyncio Pipeline + orjson I/O）
├── README.md                  # 本说明文档
└── web_search/                # 核心业务逻辑包
    ├── __init__.py
    ├── tool_api.py            # 工具 API 编排层（缓存 + 竞速搜索 + Token 压缩抓取的顶层封装）
    ├── config/                # 基础定义与配置
    │   ├── __init__.py
    │   ├── abstract.py        # SearchEngine 抽象基类（统一搜索引擎规范）
    │   ├── model.py           # SearchResult 数据模型（title/link/snippet/source_engine/is_ad）
    │   └── logging_config.py  # loguru 全局日志配置（异步控制台 + 文件轮转）
    └── server/                # 服务端核心实现
        ├── __init__.py
        ├── aggregator.py      # 竞速聚合器与全局单例 BM25Ranker（First-N 熔断 / 去重 / BM25 重排）
        ├── implement.py       # 六大搜索引擎实现（Bing / Baidu / Toutiao / DuckDuckGo / Bili / Tavily）
        ├── cache.py           # 内存 + Redis 双层缓存（基于 orjson 高性能序列化）
        ├── crawl.py           # webclaw 异步子进程抓取 + 静态降级 + 滑动窗口切块算法
        └── filter.py          # 语言感知相关性过滤与广告识别（jieba 词性分词）

```

---

## 3. 环境依赖与运行说明

- **Python**：3.10+（推荐基于 `uv` 管理依赖环境）；
- **系统工具**：需在系统环境安装并配置好 `webclaw` CLI 可执行文件；
- **Redis**：默认连接 `localhost:6379`（可在 `web_search/tool_api.py` 调整）。Redis 异常时自动降级跳过，不阻断主流程；
- **Python 第三方依赖**：

| 依赖                      | 用途                                          |
| ------------------------- | --------------------------------------------- |
| `redis`                   | 异步 Redis 客户端（缓存层）                   |
| `orjson`                  | 高性能二进制 JSON 序列化与反序列化            |
| `curl_cffi`               | 伪装 Chrome120 TLS 指纹发起引擎与静态抓取请求 |
| `httpx`                   | 静态降级拉取（带 SSL 容错与重试机制）         |
| `html2text`               | 静态 HTML 清洗转换为结构化 Markdown           |
| `beautifulsoup4` + `lxml` | 搜索引擎结果页面解析                          |
| `jieba`                   | 中文/中英混合分词与关键词词性提取             |
| `ddgs`                    | DuckDuckGo 搜索                               |
| `bilibili-api-python`     | B 站视频搜索                                  |
| `loguru`                  | 全局异步日志管理                              |

安装命令：

```bash
pip install redis orjson curl_cffi httpx html2text beautifulsoup4 lxml jieba ddgs bilibili-api-python loguru

```

运行示例：

```bash
# 1. 完整 Pipeline：搜索 + BM25重排 + webclaw抓取 + Token滑动切块压缩
python main.py --query "Python asyncio 异步编程最佳实践" --topk 3

# 2. 纯搜索模式：快速获取重排后的摘要与链接
python main.py --query "LangChain Agent 开发" --mode search --topk 5

# 3. 纯抓取模式：抓取单个网页正文
python main.py --url https://news.ycombinator.com/ --mode crawl

# 4. 禁用缓存与禁用 Token 压缩（返回完整全文）
python main.py --query "Rust 异步并发" --no-cache --no-compress

```

---

## 4. 命令行参数 (CLI Arguments)

| 参数名          | 简写 | 类型     | 默认值     | 说明                                                                                  |
| --------------- | ---- | -------- | ---------- | ------------------------------------------------------------------------------------- |
| `--query`       | `-q` | `string` | `None`     | 搜索关键词（在 `pipeline` 和 `search` 模式下**必填**）                                |
| `--mode`        | `-m` | `string` | `pipeline` | 工作模式：`pipeline`（搜索+重排+切块抓取）、`search`（仅搜索）、`crawl`（仅抓取 URL） |
| `--topk`        | `-k` | `int`    | `3`        | 返回的搜索结果数量（默认 3 条）                                                       |
| `--url`         | `-u` | `string` | `None`     | 指定抓取的单个 URL（在 `crawl` 模式下**必填**）                                       |
| `--no-cache`    | -    | `flag`   | `False`    | 显式禁用内存 / Redis 缓存，强制发起实时网络请求                                       |
| `--no-compress` | -    | `flag`   | `False`    | 禁用正文滑动切块与 Token 压缩，保留完整正文内容                                       |

---

## 5. AI Agent / 平台调用示例 (ProcessUtil)

### 场景 A：【推荐】搜索并自动抓取网页全文 (Pipeline 模式)

获取经 BM25 筛选与 Token 压缩的高价值上下文：

```python
ProcessUtil.run_python(
    script="main.py",
    args=["--query", "Python asyncio 异步编程", "--topk", "3"],
    sync=True
)

```

### 场景 B：仅搜索链接与生成 LLM 简报 (Search 模式)

```python
ProcessUtil.run_python(
    script="main.py",
    args=["--query", "LangChain Agent 开发", "--mode", "search", "--topk", "5"],
    sync=True
)

```

### 场景 C：已知目标 URL，抓取网页 Markdown 正文 (Crawl 模式)

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
      "markdown_content": "# Python Asyncio 完全指南\n\nAsyncio 是 Python 用于编写并发代码的库...\n\n...\n\n### 事件循环与 Task 调度\n使用 asyncio.create_task 并发调度任务..."
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

## 7. 异常与错误处理 (Stderr)

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
│ 阶段一：竞速聚合搜索 (aggregated_web_search_tool)             │
│  1. 查缓存（内存 → Redis orjson 极速反序列化）                │
│  2. 并发请求 6 大引擎（Bing/Baidu/Toutiao/DDG/Bili/Tavily）    │
│  3. First-N 竞速熔断：结果达标立即 cancel 慢引擎任务          │
│  4. URL 规范化与标题全局去重                                │
│  5. 全局单例 BM25Ranker 语义相关性打分重排                   │
│  6. 回写内存 + Redis（TTL 1h）                               │
└─────────────────────────────────────────────────────────────┘
   │  有效链接列表
   ▼
┌─────────────────────────────────────────────────────────────┐
│ 阶段二：抓取与 Token 压缩 (crawl_batch2md_tool)              │
│  1. Redis MGET 批量查 URL 内容缓存                          │
│  2. 未命中 → 异步调起 webclaw CLI 批量抓取（-f llm 格式）    │
│     （失败自动降级为 httpx SSL 容错拉取 + html2text 解析）   │
│  3. 回写 Redis（TTL 24h）                                    │
│  4. 滑动窗口切块（Chunking）+ BM25 提取 Top 2~3 个相关段落   │
│  5. 组装 aggregated_markdown 投喂大模型                      │
└─────────────────────────────────────────────────────────────┘
   │
   ▼
orjson 快速输出 JSON 到 stdout

```

### 8.2 缓存与低内存设计

| 维度         | 搜索级缓存 (`search_cache`)                                                     | URL 内容级缓存 (`web_content`)    |
| ------------ | ------------------------------------------------------------------------------- | --------------------------------- |
| **Key 生成** | Query 归一化（转小写/去标点/合并空白）→ MD5 前 16 位 + TopK 向上对齐（5/10/20） | URL 的 SHA256 哈希                |
| **Key 示例** | `search_cache:f0e2a3b1c4d5:5`                                                   | `web_content:3a8f...`             |
| **存储介质** | 本地字典内存 + Redis（`orjson` 序列化）                                         | Redis（单条 `set` / 批量 `mget`） |
| **过期时间** | 默认 1 小时                                                                     | 默认 24 小时                      |

---

## 9. 注意事项

- **外部依赖**：请确保宿主机已安装 `webclaw` CLI 并已加入全局 `PATH`。
- **降级机制**：若 `webclaw` 执行超时或失败，系统会自动无缝切换至 `httpx` + `html2text` 静态抓取通道。
- **网络波动**：DuckDuckGo 与海外站点在部分网络环境下可能存在连通性问题，系统已内置 First-N 竞速熔断与全局超时防护，不会拖慢整体响应。
