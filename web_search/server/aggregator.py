"""aggregator module.

FILENAME    : aggregator.py
Date        : 2026/08/14 12:14:45
Author      : Huijian Qin
Version     : 1.0.0
Description : 多搜索引擎并发聚合器：实现并发召回、去重、融合打分与 TopN 裁决

Attributes:


Example:
    >>> from aggregator import
    >>>

"""

import asyncio
from typing import List
from web_search.config.abstract import SearchEngine
from web_search.config.model import SearchResult
from web_search.server.filter import extract_keywords
from web_search.config.logging_config import logger


class SearchAggregator:
    def __init__(self, engines: List[SearchEngine]):
        self.engines = engines

    async def aggregate_search(
        self, query: str, topk: int, timeout: int = 10
    ) -> List[SearchResult]:
        """并发请求所有搜索引擎，并进行合并、去重、打分重排"""
        logger.info(
            f"[Aggregator] 开始并发聚合搜索: query='{query}', 引擎数={len(self.engines)}"
        )

        # 1. 并发打向多个搜索引擎 (对异常进行 return_exceptions 容错处理)
        tasks = [
            asyncio.create_task(engine.search(query, topk)) for engine in self.engines
        ]
        done, pending = await asyncio.wait(tasks, timeout=timeout)
        for p in pending:
            p.cancel()

        results: list[SearchResult] = []
        for task in done:
            try:
                res_list = task.result()
                if isinstance(res_list, list):
                    for res in res_list:
                        # 过滤掉非空或无效的 SearchResult
                        if (
                            res
                            and getattr(res, "link", None)
                            and getattr(res, "title", None)
                        ):
                            results.append(res)
            except Exception as e:
                logger.error(f"[Aggregator] 引擎任务异常: {e}")

        # 2. 合并与去重 (按规范化的 URL 和 Title 进行去重)
        deduplicated_results: List[SearchResult] = []
        seen_links = set()
        seen_titles = set()

        for res in results:
            if not res.link or not res.title:
                continue
            # 清理 URL 尾部斜杠，防止规范化差异
            norm_link = res.link.rstrip("/")
            norm_title = res.title.strip().lower()

            if norm_link in seen_links or norm_title in seen_titles:
                continue

            seen_links.add(norm_link)
            seen_titles.add(norm_title)
            deduplicated_results.append(res)

        # 3. 融合打分与排序
        scored_results = self._rank_results(query, deduplicated_results)

        # 4. 截取 TopN
        final_results = scored_results[:topk]
        logger.info(
            f"[Aggregator] 聚合完成: 原始={len(results)} 条, 去重后={len(deduplicated_results)} 条, 返回 Top{len(final_results)}"
        )
        return final_results

    def _rank_results(
        self, query: str, results: List[SearchResult]
    ) -> List[SearchResult]:
        q_keywords = extract_keywords(query)
        q_lower = query.lower()

        def calculate_score(item: SearchResult) -> float:
            score = 0.0
            t_lower = item.title.lower()
            s_lower = item.snippet.lower() if item.snippet else ""

            # 1. 完整 Query 包含加权
            if q_lower in t_lower:
                score += 0.5
            if q_lower in s_lower:
                score += 0.2

            # 2. 关键词匹配加权
            if q_keywords:
                t_keywords = extract_keywords(item.title)
                s_keywords = extract_keywords(item.snippet)
                title_hits = len(q_keywords & t_keywords)
                snippet_hits = len(q_keywords & s_keywords)

                score += (title_hits / len(q_keywords)) * 0.4
                score += (snippet_hits / len(q_keywords)) * 0.2

            return score

        return sorted(results, key=calculate_score, reverse=True)
