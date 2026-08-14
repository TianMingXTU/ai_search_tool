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

from web_search.config.model import SearchResult
from web_search.config.abstract import SearchEngine
from web_search.server.implement import (
    BingEngine,
    BaiduEngine,
    ToutiaoEngine,
    DuckDuckGoEngine,
    BiliEngine,
)
from web_search.server.crawl import crawl2md, crawl_batch2md
from web_search.server.cache import SearchCache
from web_search.server.aggregator import SearchAggregator
from web_search.config.logging_config import setup_logger, logger

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
    links: List[str], format_as_text: bool = True, use_cache: bool = True
) -> Union[str, Dict[str, str]]:
    """带 Redis 缓存保护的批量并发网页抓取工具"""
    if not links:
        return "" if format_as_text else {}

    final_results: Dict[str, str] = {}
    uncached_links: List[str] = []

    # 1. 尝试从 Redis 批量读取缓存 (MGET)
    if use_cache:
        cached_map = await global_cache.get_batch_url_contents(links)
        for url in links:
            content = cached_map.get(url)
            if content:
                final_results[url] = content
            else:
                uncached_links.append(url)

        hit_count = len(links) - len(uncached_links)
        logger.info(f"[crawl_batch2md_tool] URL 缓存命中: {hit_count}/{len(links)}")
    else:
        uncached_links = links

    # 2. 对未命中的 URL 触发真实的底层 Chromium 爬虫抓取
    if uncached_links:
        logger.info(
            f"[crawl_batch2md_tool] 启动爬取未缓存 URL，数量: {len(uncached_links)}"
        )
        newly_crawled_map = await crawl_batch2md(uncached_links)  # [cite: 13]

        # 3. 异步回写 Redis 缓存 (设置 24 小时 TTL)
        if use_cache and newly_crawled_map:
            await global_cache.set_batch_url_contents(newly_crawled_map, ttl=86400)

        # 合并新抓取到的结果
        final_results.update(newly_crawled_map)

    if not format_as_text:
        return final_results

    # 4. 在内存中格式化拼接 Prompt 文本
    formatted_chunks = []
    for idx, (url, content) in enumerate(final_results.items(), 1):
        chunk = f"### [Document {idx}] URL: {url}\n\n{content}\n"
        formatted_chunks.append(chunk)

    aggregated_text = "\n" + "=" * 40 + "\n\n" + "\n\n".join(formatted_chunks)
    return aggregated_text


if __name__ == "__main__":
    import asyncio

    async def main():
        print("=== 1. 测试多源聚合搜索 ===")
        search_res = await aggregated_web_search_tool(
            " 0基础，学AI，月薪过万，就来黑马程序员", topk=3
        )
        links = [item.link for item in search_res if item.link]
        print(f"召回链接列表: {links}\n")

        print("=== 2. 测试批量并发网页抓取 ===")
        if links:
            batch_text = await crawl_batch2md_tool(links, format_as_text=True)
            print(f"批量抓取拼接结果前 300 字符:\n{batch_text[:300]}...\n")

    asyncio.run(main())
