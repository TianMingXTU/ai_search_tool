"""main module.

FILENAME    : main.py
Date        : 2026/08/18 21:47:21
Author      : Huijian Qin
Version     : 1.0.3
Description : bigOClaw 平台 CLI 工具入口，集成了带 Redis 二级缓存、BM25 竞速聚合搜索与 Token 压缩网页抓取 Pipeline

Attributes:


Example:
    >>> from main import
    >>>

"""

import argparse
import asyncio
from pathlib import Path
import sys
import orjson

# 将当前工具根目录加入 sys.path，保证能够正常 import web_search 模块
current_dir = Path(__file__).resolve().parent
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))

from web_search.tool_api import (
    aggregated_web_search_tool,
    crawl_batch2md_tool,
    crawl2md_tool,
    format_results_for_llm,
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="基于 BM25 竞速重排与轻量 Token 压缩的 AI 聚合搜索与抓取工具"
    )
    parser.add_argument(
        "--query",
        "-q",
        type=str,
        default=None,
        help="搜索关键词（当 mode=pipeline 或 search 时必填）",
    )
    parser.add_argument(
        "--url",
        "-u",
        type=str,
        default=None,
        help="指定抓取的单个 URL（当 mode=crawl 时指定）",
    )
    parser.add_argument(
        "--topk",
        "-k",
        type=int,
        default=3,
        help="返回的搜索结果条数 (默认 3)",
    )
    parser.add_argument(
        "--mode",
        "-m",
        type=str,
        choices=["pipeline", "search", "crawl"],
        default="pipeline",
        help=(
            "工作模式: 'pipeline'(默认: 搜索+智能抓取全文+Token压缩),"
            " 'search'(仅搜索), 'crawl'(仅抓取指定URL)"
        ),
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="禁用 Redis 缓存，强制重新发起网络搜索与抓取",
    )
    parser.add_argument(
        "--no-compress",
        action="store_true",
        help="禁用正文滑动切块与 Token 压缩，返回完整正文",
    )
    return parser.parse_args()


async def run_pipeline(args):
    use_cache = not args.no_cache
    compress_tokens = not args.no_compress

    # ---------------------------------------------------------
    # 模式 1：pipeline (聚合搜索 -> BM25重排 -> 缓存/抓取 -> Token切块压缩 -> 组装上下文)
    # ---------------------------------------------------------
    if args.mode == "pipeline":
        if not args.query:
            raise ValueError("在 'pipeline' 模式下，必须提供 --query 参数！")

        # 1. 阶段一：多引擎竞速聚合搜索与 BM25 排序 (带 Redis 搜索级缓存)
        search_results = await aggregated_web_search_tool(
            query=args.query, topk=args.topk, use_cache=use_cache
        )

        valid_links = [item.link for item in search_results if item and item.link]

        markdown_contents = {}
        aggregated_markdown = ""

        # 2. 阶段二：批量抓取正文并进行 Query 相关的 Token 切块压缩
        if valid_links:
            markdown_contents = await crawl_batch2md_tool(
                links=valid_links,
                query=args.query,
                format_as_text=False,
                use_cache=use_cache,
                compress_tokens=compress_tokens,
            )

            # 在内存中高效拼装喂给大模型的 Context
            formatted_chunks = []
            for idx, (url, content) in enumerate(markdown_contents.items(), 1):
                chunk = f"### [Document {idx}] URL: {url}\n\n{content}\n"
                formatted_chunks.append(chunk)

            aggregated_markdown = (
                "\n" + "=" * 40 + "\n\n" + "\n\n".join(formatted_chunks)
            )

        # 3. 组装结构化数据
        results_data = []
        for item in search_results:
            results_data.append(
                {
                    "title": item.title,
                    "link": item.link,
                    "snippet": item.snippet,
                    "source_engine": item.source_engine,
                    "markdown_content": markdown_contents.get(
                        item.link, "内容抓取失败"
                    ),
                }
            )

        return {
            "status": "success",
            "mode": "pipeline",
            "query": args.query,
            "count": len(results_data),
            "results": results_data,
            "llm_search_summary": format_results_for_llm(search_results),  # 格式化简报
            "aggregated_markdown": aggregated_markdown,  # 供大模型直接消费的高相关正文
        }

    # ---------------------------------------------------------
    # 模式 2：search (仅搜索与重排，不抓取正文)
    # ---------------------------------------------------------
    elif args.mode == "search":
        if not args.query:
            raise ValueError("在 'search' 模式下，必须提供 --query 参数！")

        search_results = await aggregated_web_search_tool(
            query=args.query, topk=args.topk, use_cache=use_cache
        )

        return {
            "status": "success",
            "mode": "search",
            "query": args.query,
            "count": len(search_results),
            "results": [
                {
                    "title": item.title,
                    "link": item.link,
                    "snippet": item.snippet,
                    "source_engine": item.source_engine,
                }
                for item in search_results
            ],
            "llm_search_summary": format_results_for_llm(search_results),
        }

    # ---------------------------------------------------------
    # 模式 3：crawl (仅抓取单个指定 URL)
    # ---------------------------------------------------------
    elif args.mode == "crawl":
        if not args.url:
            raise ValueError("在 'crawl' 模式下，必须提供 --url 参数！")

        content_map = await crawl_batch2md_tool(
            links=[args.url],
            query=args.query,
            format_as_text=False,
            use_cache=use_cache,
            compress_tokens=compress_tokens,
        )
        url_markdown = content_map.get(args.url, "内容抓取失败")

        return {
            "status": "success",
            "mode": "crawl",
            "url": args.url,
            "markdown_content": url_markdown,
        }


def main():
    args = parse_args()
    try:
        output = asyncio.run(run_pipeline(args))

        # 使用 orjson 快速序列化并输出至 stdout 供 AI Agent / 平台直接消费
        sys.stdout.buffer.write(orjson.dumps(output))
        sys.stdout.buffer.write(b"\n")
        sys.stdout.flush()
        sys.exit(0)

    except Exception as e:
        error_payload = {
            "status": "error",
            "message": str(e),
        }
        sys.stderr.buffer.write(orjson.dumps(error_payload))
        sys.stderr.buffer.write(b"\n")
        sys.stderr.flush()
        sys.exit(1)


if __name__ == "__main__":
    main()
