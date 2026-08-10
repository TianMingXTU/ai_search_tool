"""crawl module.

FILENAME    : crawl.py
Date        : 2026/08/10 18:32:46
Author      : Huijian Qin
Version     : 1.0.0
Description :抓取网页内容

Attributes:


Example:
    >>> from crawl import crawl2md
    >>>

"""

import asyncio
from crawl4ai import AsyncWebCrawler


async def crawl2md(link: str):
    async with AsyncWebCrawler() as crawler:
        try:
            result = await crawler.arun(url=link)
            print(type(result.markdown))
            return result.markdown
        except Exception as e:
            return "web内容获取失败!"


if __name__ == "__main__":
    asyncio.run(crawl2md("https://docs.crawl4ai.com/"))
