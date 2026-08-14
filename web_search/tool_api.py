"""tool_api module.

FILENAME    : tool_api.py
Date        : 2026/08/10 19:15:57
Author      : Huijian Qin
Version     : 1.0.0
Description : 工具函数接口

Attributes:


Example:
    >>> from tool_api import web_search_tool
    >>>

"""

from typing import Any, List, Literal

from model import SearchResult
from abstract import SearchEngine
from implement import (
    BingEngine,
    BaiduEngine,
    ToutiaoEngine,
    DuckDuckGoEngine,
    BiliEngine,
)
from crawl import crawl2md
from logging_config import setup_logger, logger

setup_logger("INFO")


async def web_search_tool(
    query: str, topk: str, search_engine: SearchEngine
) -> List[SearchResult]:
    """网络搜索工具

    Args:
        query (str): 搜索关键字
        topk (str): 返回结果的数量
        search_engine (SearchEngine): SearchEngine的具体实现

    Returns:
        List[SearchResult]: SearchResult
    """
    search_obj: List[SearchResult] = await search_engine.search(query, topk)
    return search_obj


async def crawl2md_tool(link: str) -> str:
    """爬取url具体的内容

    Args:
        link (str): url网址

    Returns:
        str: 网页内容
    """
    md_obj: Any | Literal["web内容获取失败!"] = await crawl2md(link)
    return str(md_obj)
