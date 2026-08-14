"""tool_api module.

FILENAME    : tool_api.py
Date        : 2026/08/14 12:15:40
Author      : Huijian Qin
Version     : 1.0.2
Description : 集成多源并发聚合、Redis 缓存编排与批量并发抓取

Attributes:


Example:
    >>> from tool_api import aggregated_web_search_tool, crawl_batch2md_tool
    >>>

"""

from typing import Any, List, Dict, Literal, Optional, Union

from config.model import SearchResult
from config.abstract import SearchEngine
from server.implement import (
    BingEngine,
    BaiduEngine,
    ToutiaoEngine,
    DuckDuckGoEngine,
    BiliEngine,
)
from server.crawl import crawl2md, crawl_batch2md
from server.cache import SearchCache
from server.aggregator import SearchAggregator
from config.logging_config import setup_logger, logger

setup_logger("INFO")

# 全局初始化 Redis 缓存实例 (可根据需要配置 host/port/password)
global_cache = SearchCache(host="localhost", port=6379, ttl=3600)

# 默认并发调用的 5 个搜索引擎实例
DEFAULT_ENGINES: List[SearchEngine] = [
    BingEngine(),
    BaiduEngine(),
    ToutiaoEngine(),
    DuckDuckGoEngine(),
    BiliEngine(),
]

global_aggregator = SearchAggregator(engines=DEFAULT_ENGINES)


async def aggregated_web_search_tool(
    query: str, topk: int = 5, use_cache: bool = True
) -> List[SearchResult]:
    """聚合网络搜索工具：带 Redis 缓存 + 多搜索引擎并发聚合 + 去重打分重排

    Args:
        query (str): 搜索关键字
        topk (int): 返回 TopN 结果数量，默认为 5
        use_cache (bool): 是否使用 Redis 缓存保护

    Returns:
        List[SearchResult]: 聚合后的搜索结果
    """
    # 1. 尝试从缓存获取
    if use_cache:
        cached_res = await global_cache.get(query, topk)
        if cached_res is not None:
            return cached_res

    # 2. 缓存未命中，触发多源并发聚合搜索
    results = await global_aggregator.aggregate_search(query, topk)

    # 3. 写入缓存
    if use_cache and results:
        await global_cache.set(query, topk, results)

    return results


async def web_search_tool(
    query: str, topk: int, search_engine: SearchEngine
) -> List[SearchResult]:
    """单搜索引擎工具"""
    search_obj = await search_engine.search(query, topk)
    return search_obj if isinstance(search_obj, list) else []


async def crawl2md_tool(link: str) -> str:
    """爬取 url 具体的内容"""
    md_obj: Any | Literal["web内容获取失败!"] = await crawl2md(link)
    return str(md_obj)


async def crawl_batch2md_tool(
    links: List[str], format_as_text: bool = True
) -> Union[str, Dict[str, str]]:
    """批量并发爬取多个 url 网址的内容

    依托底层 Chromium 实例复用与 crawl4ai 原生 arun_many 异步并发，一次性抓取全部内容

    Args:
        links (List[str]): URL 地址列表
        format_as_text (bool):
            - True: 返回拼装好、带文档序号分隔符的大文本，便于直接投喂给 LLM
            - False: 返回 Dict[url, markdown_content] 映射字典

    Returns:
        Union[str, Dict[str, str]]: 格式化 Markdown 拼接文本 或 URL -> Markdown 内容字典
    """
    if not links:
        return "" if format_as_text else {}

    logger.info(f"[crawl_batch2md_tool] 启动批量并发抓取，URL 数量: {len(links)}")

    # 调取 crawl.py 中的批量并发抓取逻辑
    batch_res: Dict[str, str] = await crawl_batch2md(links)

    if not format_as_text:
        return batch_res

    # 格式化拼接为便于 LLM 上下文阅读的 Prompt 结构
    formatted_chunks = []
    for idx, (url, content) in enumerate(batch_res.items(), 1):
        chunk = f"### [Document {idx}] URL: {url}\n\n{content}\n"
        formatted_chunks.append(chunk)

    aggregated_text = "\n" + "=" * 40 + "\n\n" + "\n\n".join(formatted_chunks)
    logger.info(
        f"[crawl_batch2md_tool] 批量抓取完成，生成文本总长度: {len(aggregated_text)} 字符"
    )

    return aggregated_text


if __name__ == "__main__":
    import asyncio

    async def main():
        print("=== 1. 测试多源聚合搜索 ===")
        search_res = await aggregated_web_search_tool(
            "月薪过万，就来黑马程序员", topk=3
        )
        links = [item.link for item in search_res if item.link]
        print(f"召回链接列表: {links}\n")

        print("=== 2. 测试批量并发网页抓取 ===")
        if links:
            batch_text = await crawl_batch2md_tool(links, format_as_text=True)
            print(f"批量抓取拼接结果前 300 字符:\n{batch_text[:300]}...\n")

    asyncio.run(main())
