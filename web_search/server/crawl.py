"""
FILENAME    : crawl.py
Date        : 2026/08/14 10:32:46
Author      : Huijian Qin
Version     : 1.0.1
Description : 高性能单例网页抓取模块，基于 crawl4ai 实现浏览器复用与批量并发抓取

Example:
    >>> from crawl import crawl2md, crawl_batch2md, close_crawler
    >>> markdown_text = await crawl2md("https://docs.crawl4ai.com/")
"""

import re
import asyncio
from typing import List, Optional, Dict
from curl_cffi.requests import AsyncSession
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode


class CrawlerManager:
    """全局单例爬虫管理器，实现 Chromium 实例复用"""

    _instance: Optional[AsyncWebCrawler] = None
    _lock = asyncio.Lock()

    @classmethod
    async def get_crawler(cls) -> AsyncWebCrawler:
        """异步单例懒加载获取 AsyncWebCrawler 实例"""
        if cls._instance is None:
            async with cls._lock:
                if cls._instance is None:
                    # 可以在此配置无头浏览器参数，避免不必要的图像渲染以提升速度
                    browser_config = BrowserConfig(
                        headless=True,
                        verbose=False,
                    )
                    crawler = AsyncWebCrawler(config=browser_config)
                    await crawler.start()
                    cls._instance = crawler
        return cls._instance

    @classmethod
    async def close(cls):
        """显式释放浏览器资源"""
        async with cls._lock:
            if cls._instance is not None:
                await cls._instance.close()
                cls._instance = None


async def crawl2md(link: str) -> str:
    """
    抓取单个网页并转为 Markdown

    :param link: 网页地址
    :return: 对应的 Markdown 文本或失败提示
    """
    # 1. 优先使用极轻量级的 curl_cffi 进行静态拉取（内存占用 < 10MB）
    try:
        async with AsyncSession(impersonate="chrome120") as session:
            resp = await session.get(link, timeout=6)
            if resp.status_code == 200 and len(resp.text) > 200:
                clean_text = _html_to_clean_text(resp.text)
                if len(clean_text) > 100:
                    return clean_text
    except Exception:
        pass
    # 2. 静态提取失败且支持无头浏览器时，再调取 crawl4ai
    try:
        crawler = await CrawlerManager.get_crawler()

        # 配置运行参数
        run_config = CrawlerRunConfig(cache_mode=CacheMode.ENABLED)

        result = await crawler.arun(url=link, config=run_config)

        if result and result.success:
            # crawl4ai 的 markdown 属性通常为 MarkdownGenerationResult 对象或 str
            md_content = result.markdown
            if hasattr(md_content, "raw_markdown"):
                return md_content.raw_markdown
            return str(md_content) if md_content else ""
        return "web内容获取失败: 页面加载未成功"
    except Exception as e:
        return f"web内容获取失败: {str(e)}"


def _html_to_clean_text(html: str) -> str:
    """极轻量级 HTML 纯文本提取（无大内存依赖）"""
    # 移除 script 与 style 标签
    text = re.sub(
        r"<(script|style).*?>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE
    )
    # 转换换行标签
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</(p|div|h[1-6]|li|tr)>", "\n", text, flags=re.IGNORECASE)
    # 去除所有 HTML 标签
    text = re.sub(r"<[^>]+>", "", text)
    # 清理多余空行
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


async def crawl_batch2md(links: List[str]) -> Dict[str, str]:
    """
    批量并发抓取多个网页并返回 URL -> Markdown 的字典映射

    :param links: 网页地址列表
    :return: Dict[url, markdown_content]
    """
    if not links:
        return {}

    try:
        crawler = await CrawlerManager.get_crawler()
        run_config = CrawlerRunConfig(cache_mode=CacheMode.ENABLED)

        # 使用 crawl4ai 原生的 arun_many 进行多并发高效率抓取
        results = await crawler.arun_many(urls=links, config=run_config)

        res_map = {}
        for res in results:
            if res and res.success:
                md_content = res.markdown
                raw_md = (
                    md_content.raw_markdown
                    if hasattr(md_content, "raw_markdown")
                    else str(md_content)
                )
                res_map[res.url] = raw_md
            else:
                res_map[res.url] = "web内容获取失败!"
        return res_map
    except Exception as e:
        return {link: f"web内容获取失败: {str(e)}" for link in links}


async def close_crawler():
    """供外部服务程序（如 FastAPI / 系统退出）调用的清理 Hook"""
    await CrawlerManager.close()


if __name__ == "__main__":

    async def main():
        # 测试单页面抓取
        print("=== 测试单页面 ===")
        md = await crawl2md("https://docs.crawl4ai.com/")
        print(f"提取结果类型: {type(md)}, 前 100 字符:\n{md[:100]}...\n")

        # 测试批量并发抓取（复用同一个浏览器实例）
        print("=== 测试批量抓取 ===")
        urls = ["https://docs.crawl4ai.com/", "https://python.org"]
        batch_res = await crawl_batch2md(urls)
        for url, content in batch_res.items():
            print(f"URL: {url} -> 长度: {len(content)}")

        # 显式关闭底层 Chromium 进程
        await close_crawler()

    asyncio.run(main())
