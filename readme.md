# 多源并发聚合搜索与网页全文抓取工具 (AI Search & Crawl Tool)

## 1. 工具简介

本工具是为大模型/AI Agent 量身打造的**端到端（End-to-End）信息检索与抓取系统**。

内部采用两阶段（Two-Stage）Pipeline 架构：

1. **多源并发召回（Search）**：并发调度 Bing、Baidu、头条、B站、DuckDuckGo 等搜索引擎，结合 Redis 哈希缓存与智能中英文分词/广告过滤。
2. **批量并发抓取（Crawl）**：基于单例 Chromium 浏览器复用，将召回的 TopK 网页并行抓取并清洗为高质量 Markdown 格式。

---

## 2. 目录结构与文件说明

```text
tools/ai_search/
├── main.py              # 平台 CLI 接口入口（支持 argparse、json stdout 交互）
├── README.md            # 本说明文档
├── requirements.txt     # 项目依赖配置
└── web_search/          # 核心业务逻辑包
    ├── tool_api.py      # 工具 API 编排层
    ├── filter.py        # 语言感知与广告过滤模块
    ├── crawl.py         # 基于 Playwright/crawl4ai 的并发爬虫
    └── server/
        ├── aggregator.py # 多源并发聚合重排
        ├── implement.py  # 各搜索引擎底座实现
        └── cache.py      # Redis 归一化缓存

```

---

## 3. 命令行参数 (CLI Arguments)

| 参数名       | 简写 | 类型     | 默认值     | 说明                                                                                  |
| ------------ | ---- | -------- | ---------- | ------------------------------------------------------------------------------------- |
| `--query`    | `-q` | `string` | `None`     | 搜索关键词（在 `pipeline` 和 `search` 模式下**必填**）                                |
| `--mode`     | `-m` | `string` | `pipeline` | 工作模式：`pipeline`（搜索并自动抓取全文）、`search`（仅搜索）、`crawl`（仅抓取 URL） |
| `--topk`     | `-k` | `int`    | `3`        | 返回的搜素结果数量（默认 3 条）                                                       |
| `--url`      | `-u` | `string` | `None`     | 指定爬取的单个 URL（在 `crawl` 模式下**必填**）                                       |
| `--no-cache` | -    | `flag`   | `False`    | 附加该参数可显式禁用 Redis 缓存，强制实时搜索                                         |

---

## 4. AI 员工调用示例 (ProcessUtil)

### 场景 A：【推荐】搜索并自动抓取网页全文 (Pipeline 模式)

一步到位获取包含标题、链接、摘要以及完整 Markdown 正文的结构化上下文：

```python
ProcessUtil.run_python(
    script="tools/ai_search/main.py",
    args=["--query", "Python asyncio 异步编程", "--topk", "3"],
    sync=True
)

```

### 场景 B：仅搜索链接与摘要 (Search 模式)

快速获取检索列表，省流量与延迟：

```python
ProcessUtil.run_python(
    script="tools/ai_search/main.py",
    args=["--query", "LangChain Agent 开发", "--mode", "search", "--topk", "5"],
    sync=True
)

```

### 场景 C：已知目标 URL，精准抓取网页 Markdown 正文 (Crawl 模式)

```python
ProcessUtil.run_python(
    script="tools/ai_search/main.py",
    args=["--url", "[https://news.ycombinator.com/](https://news.ycombinator.com/)", "--mode", "crawl"],
    sync=True
)

```

---

## 5. 输出 JSON 数据格式说明

标准执行成功时通过 `stdout` 返回 JSON 对象：

### Pipeline 模式返回样例：

```json
{
  "status": "success",
  "mode": "pipeline",
  "query": "Python asyncio 异步编程",
  "count": 3,
  "results": [
    {
      "title": "Python Asyncio 异步编程完全指南",
      "link": "[https://example.com/asyncio-guide](https://example.com/asyncio-guide)",
      "snippet": "本文详细介绍了 Python 中 asyncio 事件循环与协程的使用...",
      "source_engine": "BingEngine",
      "markdown_content": "# Python Asyncio 完全指南\n\nAsyncio 是 Python 标准库中用于编写并发代码的库..."
    }
  ],
  "aggregated_markdown": "========================================\n\n### [Document 1] URL: [https://example.com/asyncio-guide](https://example.com/asyncio-guide)\n\n# Python Asyncio 完全指南..."
}
```

> **提示**：大模型（LLM）回答复杂问题时，可优先读取最外层的 `aggregated_markdown` 字段，该字段已按文档序号拼接好标准 Prompt 结构，直接投喂上下文效果最佳。

---

## 6. 异常与错误处理 (Stderr)

如果运行时抛出异常或参数错误，退出码为非 0（`exit status 1`），错误信息将以 JSON 格式输出至 `stderr`：

```json
{
  "status": "error",
  "message": "在 'pipeline' 模式下，必须提供 --query 参数！"
}
```
