"""
FILENAME    : main.py
Description : bigOClaw 平台 CLI 工具入口，集成了【带 Redis 二级缓存的搜索 + 网页全文抓取】完整 Pipeline，输出 JSON 到 stdout
"""

import argparse
import asyncio
import json
from pathlib import Path
import sys

# 将当前工具根目录加入 sys.path，保证能够正常 import web_search 模块
current_dir = Path(__file__).resolve().parent
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))

from web_search.tool_api import (
    aggregated_web_search_tool,
    crawl_batch2md_tool,
    crawl2md_tool,
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="带 Redis 二级缓存的多源并发聚合搜索与网页全文抓取工具"
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
        help="工作模式: 'pipeline'(默认: 搜索+智能抓取全文), 'search'(仅搜索), 'crawl'(仅抓取指定URL)",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="禁用 Redis 缓存，强制重新发起网络搜索与抓取",
    )
    return parser.parse_args()


async def run_pipeline(args):
    use_cache = not args.no_cache

    # ---------------------------------------------------------
    # 模式 1：pipeline (默认: 聚合搜索 -> 提取链接 -> 智能并发抓取/查缓存 -> 组装 Prompt)
    # ---------------------------------------------------------
    if args.mode == "pipeline":
        if not args.query:
            raise ValueError("在 'pipeline' 模式下，必须提供 --query 参数！")

        # 1. 阶段一：聚合搜索 (带搜索级缓存)
        search_results = await aggregated_web_search_tool(
            query=args.query, topk=args.topk, use_cache=use_cache
        )

        valid_links = [item.link for item in search_results if item and item.link]

        markdown_contents = {}
        aggregated_markdown = ""

        # 2. 阶段二：批量抓取全文 (带 URL 级 Redis 缓存，仅触发 1 次批量调用)
        if valid_links:
            # 抓取流程：内部自动查缓存 -> 未命中才爬取 -> 回写 Redis
            markdown_contents = await crawl_batch2md_tool(
                valid_links, format_as_text=False, use_cache=use_cache
            )

            # 在内存中快速高效拼接 Prompt 大文本（避免二次网络请求）
            formatted_chunks = []
            for idx, (url, content) in enumerate(markdown_contents.items(), 1):
                chunk = f"### [Document {idx}] URL: {url}\n\n{content}\n"
                formatted_chunks.append(chunk)

            aggregated_markdown = (
                "\n" + "=" * 40 + "\n\n" + "\n\n".join(formatted_chunks)
            )

        # 3. 组装结果结构化 JSON 抛给平台
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
            "aggregated_markdown": aggregated_markdown,  # 供大模型大上下文直接读取
        }

    # ---------------------------------------------------------
    # 模式 2：search (仅搜索，不抓取正文)
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
        }

    # ---------------------------------------------------------
    # 模式 3：crawl (仅抓取单个指定 URL)
    # ---------------------------------------------------------
    elif args.mode == "crawl":
        if not args.url:
            raise ValueError("在 'crawl' 模式下，必须提供 --url 参数！")

        # 支持查/写 URL 缓存
        content = await crawl_batch2md_tool(
            [args.url], format_as_text=False, use_cache=use_cache
        )
        url_markdown = content.get(args.url, "内容抓取失败")

        return {
            "status": "success",
            "mode": "crawl",
            "url": args.url,
            "markdown_content": url_markdown,
        }


def main():
    args = parse_args()
    try:
        # 执行异步 pipeline
        output = asyncio.run(run_pipeline(args))

        # 严格打印合法 JSON 到 stdout（平台读取此输出）
        print(json.dumps(output, ensure_ascii=False))
        sys.exit(0)

    except Exception as e:
        # 异常捕获并输出 JSON 到 stderr，抛出非 0 退出码
        error_payload = {
            "status": "error",
            "message": str(e),
        }
        sys.stderr.write(json.dumps(error_payload, ensure_ascii=False) + "\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
