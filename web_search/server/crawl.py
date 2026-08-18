"""
FILENAME    : crawl.py
Date        : 2026/08/18 20:10:00
Author      : Huijian Qin
Version     : 1.0.2
Description : 基于 webclaw (-f llm) 的高性能网页提取模块，支持正文提取、浏览器伪装、并发控制与静态拉取降级

Example:
    >>> from crawl import crawl2md, crawl_batch2md, close_crawler
    >>> markdown_text = await crawl2md("https://docs.crawl4ai.com/")
"""

import json
import re
import asyncio
import ssl
from urllib.parse import urlparse
from typing import List, Dict
import html2text
import httpx

from web_search.server.aggregator import global_ranker
from web_search.config.model import SearchResult


def extract_top_chunks(
    markdown_text: str,
    query: str,
    top_chunks_count: int = 2,
    chunk_size: int = 600,
    overlap: int = 100,
) -> str:
    """
    基于滑动窗口切分，并直接复用 BM25Ranker 提取与 Query 最相关的 TopN Chunks
    """
    text = markdown_text.strip()
    if not text or len(text) <= chunk_size:
        return text

    # 1. 严格按字符步长滑动切分 Chunk
    chunks: List[str] = []
    start = 0
    text_len = len(text)
    step = max(chunk_size - overlap, 100)

    while start < text_len:
        end = min(start + chunk_size, text_len)
        chunk = text[start:end]

        # 优先在换行处断开，避免破坏段落结构
        if end < text_len:
            last_break = chunk.rfind("\n")
            if last_break > chunk_size // 2:
                chunk = chunk[:last_break]
                start += last_break + 1
            else:
                start += step
        else:
            start += step

        chunk = chunk.strip()
        if chunk:
            chunks.append(chunk)

    if not chunks or len(chunks) <= top_chunks_count:
        return text

    # 2. 将每个 Chunk 映射为 SearchResult 对象（link 字段存入原始索引用于保序）
    pseudo_results = [
        SearchResult(
            title="",
            snippet=c,
            link=str(idx),  # 记录在原文中的绝对位置
            source_engine="Chunk",
        )
        for idx, c in enumerate(chunks)
    ]

    # 3. 调用BM25Ranker进行统一语义打分排序
    ranker = global_ranker
    ranked_results = ranker.rank(query, pseudo_results)

    # 4. 截取 TopN，并按原文顺序（link 存储的 index）重新排序，保持行文连贯
    selected_top = ranked_results[:top_chunks_count]
    selected_top.sort(key=lambda item: int(item.link))

    return "\n\n...\n\n".join([item.snippet for item in selected_top])


async def crawl2md(
    link: str,
    format_type: str = "markdown",
    only_main_content: bool = True,
    timeout: int = 15,
) -> str:
    """
    通过 webclaw CLI 抓取单个网页并提取内容

    :param link: 目标网页 URL
    :param format_type: 提取格式 ('markdown', 'llm', 'text', 'json')
    :param only_main_content: 是否只提取核心正文
    :param timeout: 超时时间（秒）
    :return: 提取的文本或失败提示
    """
    # 1. 组装 webclaw 命令参数
    cmd = [
        "webclaw",
        link,
        "-f",
        format_type,
        "-b",
        "chrome",
        "--timeout",
        str(timeout),
    ]

    if only_main_content:
        cmd.append("--only-main-content")

    # 2. 调起子进程执行
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout + 3)

        if proc.returncode == 0 and stdout:
            content = stdout.decode("utf-8", errors="ignore").strip()
            if content:
                return content
    except Exception:
        pass

    # 3. 降级处理：使用 _fetch_html_fallback 进行拉取
    try:
        clean_text = await _fetch_html_fallback(link)
        if len(clean_text) > 100:
            return clean_text
    except Exception as e:
        return f"web内容获取失败: {str(e)}"

    return "web内容获取失败: 页面加载未成功"


def _new_html2text() -> html2text.HTML2Text:
    h = html2text.HTML2Text()
    h.ignore_links = False
    h.ignore_images = True
    h.body_width = 0
    return h


def _is_ssl_error(exc: BaseException) -> bool:
    cur = exc
    while cur is not None:
        if isinstance(cur, ssl.SSLError) or "SSL" in type(cur).__name__:
            return True
        cur = cur.__cause__
    return False


async def _fetch_html_fallback(url: str, timeout: int = 10) -> str:
    """带 SSL 容错与 Content-Type 防护的静态降级拉取"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    client_args = {"timeout": timeout, "follow_redirects": True, "headers": headers}
    try:
        async with httpx.AsyncClient(**client_args) as client:
            resp = await client.get(url)
    except Exception as first_exc:
        if not _is_ssl_error(first_exc):
            raise first_exc
        async with httpx.AsyncClient(**client_args, verify=False) as client:
            resp = await client.get(url)

    resp.raise_for_status()
    ct = (resp.headers.get("content-type") or "").lower()
    if ct and not any(
        ct.startswith(t) for t in ("text/", "application/xhtml", "application/xml")
    ):
        raise ValueError(f"Unsupported Content-Type: {ct}")

    # 提取 <title> 作为 Heading 拼接到 Markdown 前
    title_m = re.search(
        r"<title[^>]*>(.*?)</title>", resp.text, re.IGNORECASE | re.DOTALL
    )
    title = re.sub(r"\s+", " ", title_m.group(1)).strip()[:200] if title_m else ""

    body = _new_html2text().handle(resp.text).strip()
    return f"# {title}\n\n{body}" if (title and body) else (title or body)


async def crawl_batch2md(
    links: List[str],
    concurrency: int = 5,
    format_type: str = "markdown",
    only_main_content: bool = True,
    timeout: int = 25,
) -> Dict[str, str]:
    """
    批量抓取多个网页并返回 URL -> 内容的映射

    :param links: 网页 URL 列表
    :param concurrency: webclaw 原生并发数
    :param format_type: 提取格式
    :param only_main_content: 是否过滤无关非正文元素
    :param timeout: 批量总超时限制
    :return: Dict[url, markdown_content]
    """
    if not links:
        return {}

    # 优先利用 webclaw 原生支持的多 URL + json 输出能力
    cmd = [
        "webclaw",
        *links,
        "-f",
        "json" if format_type == "markdown" else format_type,
        "--concurrency",
        str(concurrency),
        "-b",
        "chrome",
        "--timeout",
        str(timeout),
    ]

    if only_main_content:
        cmd.append("--only-main-content")

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout + 5)

        if proc.returncode == 0 and stdout:
            raw_output = stdout.decode("utf-8", errors="ignore").strip()
            data = json.loads(raw_output)

            # 解析 webclaw 返回的 JSON 列表格式
            if isinstance(data, list):
                res_map = {}
                for item in data:
                    url = item.get("url")
                    content = (
                        item.get("content")
                        or item.get("markdown")
                        or item.get("text")
                        or ""
                    )
                    if url:
                        res_map[url] = content
                # 补全可能缺失的 URL
                for u in links:
                    if u not in res_map or not res_map[u]:
                        res_map[u] = "web内容获取失败!"
                return res_map
            elif isinstance(data, dict):
                return {
                    u: data.get("content") or data.get("markdown") or "web内容获取失败!"
                    for u in links
                }
    except Exception:
        pass

    # 若多 URL 批量 JSON 解析失败，平滑降级为基于 Semaphore 的单任务并发抓取
    sem = asyncio.Semaphore(concurrency)

    async def _fetch_single(url: str) -> tuple[str, str]:
        async with sem:
            content = await crawl2md(
                url,
                format_type=format_type,
                only_main_content=only_main_content,
                timeout=12,
            )
            return url, content

    tasks = [_fetch_single(url) for url in links]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    res_map = {}
    for item in results:
        if isinstance(item, tuple):
            u, c = item
            res_map[u] = c
        else:
            pass

    return res_map


async def close_crawler():
    """清理 Hook（保留接口以保证上层 tool_api 兼容）"""
    pass


if __name__ == "__main__":

    async def main():
        print("=== 1. 单页面抓取测试 (LLM 模式) ===")
        md = await crawl2md(
            "https://python.org", format_type="markdown", only_main_content=True
        )
        print(f"提取结果长度: {len(md)}, 前 150 字符:\n{md[:150]}...\n")

        print("=== 2. 多页面原生批量抓取测试 ===")
        urls = ["https://python.org", "https://github.com"]
        batch_res = await crawl_batch2md(urls, concurrency=2)
        for url, content in batch_res.items():
            print(f"URL: {url} -> 长度: {len(content)}")

    asyncio.run(main())
