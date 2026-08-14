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
from abstract import SearchEngine
from model import SearchResult
from filter import extract_keywords
from logging_config import logger


class SearchAggregator:
    def __init__(self, engines: List[SearchEngine]):
        self.engines = engines

    async def aggregate_search(self, query: str, topk: int) -> List[SearchResult]:
        """并发请求所有搜索引擎，并进行合并、去重、打分重排"""
        logger.info(
            f"[Aggregator] 开始并发聚合搜索: query='{query}', 引擎数={len(self.engines)}"
        )

        # 1. 并发打向多个搜索引擎 (对异常进行 return_exceptions 容错处理)
        tasks = [engine.search(query, topk) for engine in self.engines]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        all_results: List[SearchResult] = []
        for resp in responses:
            if isinstance(resp, list):
                all_results.extend(resp)
            elif isinstance(resp, Exception):
                logger.error(f"[Aggregator] 某引擎响应异常: {resp}")

        if not all_results:
            logger.warning(f"[Aggregator] 所有引擎均未召回有效结果")
            return []

        # 2. 合并与去重 (按规范化的 URL 和 Title 进行去重)
        deduplicated_results: List[SearchResult] = []
        seen_links = set()
        seen_titles = set()

        for res in all_results:
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
            f"[Aggregator] 聚合完成: 原始={len(all_results)} 条, 去重后={len(deduplicated_results)} 条, 返回 Top{len(final_results)}"
        )
        return final_results

    def _rank_results(
        self, query: str, results: List[SearchResult]
    ) -> List[SearchResult]:
        """根据 Query 关键词在标题与摘要中的匹配度进行相关性打分"""
        q_keywords = extract_keywords(query)
        if not q_keywords:
            return results

        def calculate_score(item: SearchResult) -> float:
            score = 0.0
            t_keywords = extract_keywords(item.title)
            s_keywords = extract_keywords(item.snippet)

            # 标题关键词命中权重 (权重 0.6)
            title_hits = len(q_keywords & t_keywords)
            score += (title_hits / len(q_keywords)) * 0.6

            # 摘要关键词命中权重 (权重 0.4)
            snippet_hits = len(q_keywords & s_keywords)
            score += (snippet_hits / len(q_keywords)) * 0.4

            return score

        # 按得分从高到低排序
        return sorted(results, key=calculate_score, reverse=True)
