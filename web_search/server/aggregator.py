"""aggregator module.

FILENAME    : aggregator.py
Date        : 2026/08/18 21:05:59
Author      : Huijian Qin
Version     : 1.0.3
Description : 竞速聚合器：First-N 熔断与低内存 BM25 融合打分重排

Attributes:


Example:
    >>> from aggregator import
    >>>

"""

import math
import asyncio
from typing import List, Set, Dict
from web_search.config.abstract import SearchEngine
from web_search.config.model import SearchResult
from web_search.server.filter import extract_keywords
from web_search.config.logging_config import logger


class BM25Ranker:
    """轻量级 BM25 排序器，内存占用接近 0，纯 CPU 毫秒级计算"""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b

    def rank(self, query: str, results: List[SearchResult]) -> List[SearchResult]:
        if not results:
            return []

        q_terms = list(extract_keywords(query))
        if not q_terms:
            q_terms = [w.lower() for w in query.split() if w.strip()]
        if not q_terms:
            return results

        # 1. 构造文档词频和长度
        docs_terms: List[List[str]] = []
        doc_lengths: List[int] = []
        doc_freqs: Dict[str, int] = {term: 0 for term in q_terms}

        for item in results:
            text = f"{item.title} {item.snippet}"
            terms = list(extract_keywords(text))
            term_set = set(terms)
            for t in q_terms:
                if t in term_set:
                    doc_freqs[t] += 1
            docs_terms.append(terms)
            doc_lengths.append(len(terms) or 1)

        N = len(results)
        avgdl = sum(doc_lengths) / N if N > 0 else 1.0

        # 2. 计算 IDF
        idf: Dict[str, float] = {}
        for t in q_terms:
            n_q = doc_freqs[t]
            # 标准 BM25 平滑 IDF
            idf[t] = math.log((N - n_q + 0.5) / (n_q + 0.5) + 1.0)

        # 3. 统计 BM25 分数并融合 Title 显式命中增强
        scored_items = []
        q_lower = query.lower()

        for idx, item in enumerate(results):
            score = 0.0
            terms = docs_terms[idx]
            doc_len = doc_lengths[idx]

            # 词频统计
            tf_map: Dict[str, int] = {}
            for t in terms:
                tf_map[t] = tf_map.get(t, 0) + 1

            for t in q_terms:
                f = tf_map.get(t, 0)
                if f > 0:
                    numerator = f * (self.k1 + 1)
                    denominator = f + self.k1 * (
                        1 - self.b + self.b * (doc_len / avgdl)
                    )
                    score += idf[t] * (numerator / denominator)

            # 标题完全包含 Query 强权增强
            if q_lower in item.title.lower():
                score += 1.5

            scored_items.append((score, item))

        scored_items.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored_items]


global_ranker = BM25Ranker()


class SearchAggregator:
    def __init__(self, engines: List[SearchEngine]):
        self.engines = engines
        self.ranker = global_ranker

    async def aggregate_search(
        self, query: str, topk: int, timeout: float = 6.0
    ) -> List[SearchResult]:
        """并发请求搜索引擎，满足 First-N (topk * 2) 数量即提前截断返回"""
        logger.info(
            f"[Aggregator] 开始竞速聚合搜索: query='{query}', 引擎数={len(self.engines)}"
        )

        # 创建所有引擎的异步任务
        task_map = {
            asyncio.create_task(engine.search(query, topk)): engine
            for engine in self.engines
        }

        target_count = topk * 2  # 竞速目标召回量
        deduplicated_results: List[SearchResult] = []
        seen_links: Set[str] = set()
        seen_titles: Set[str] = set()
        total_raw_count = 0

        try:
            # as_completed 谁快先处理谁
            for future in asyncio.as_completed(task_map.keys(), timeout=timeout):
                try:
                    res_list = await future
                    if isinstance(res_list, list):
                        for res in res_list:
                            if not res or not res.link or not res.title:
                                continue
                            total_raw_count += 1

                            norm_link = res.link.rstrip("/")
                            norm_title = res.title.strip().lower()

                            if norm_link in seen_links or norm_title in seen_titles:
                                continue

                            seen_links.add(norm_link)
                            seen_titles.add(norm_title)
                            deduplicated_results.append(res)

                        # 数量达标，触发竞速熔断
                        if len(deduplicated_results) >= target_count:
                            logger.info(
                                f"[Aggregator] 命中竞速阈值 ({len(deduplicated_results)}/{target_count})，提前截断慢引擎任务！"
                            )
                            break
                except Exception as e:
                    logger.error(f"[Aggregator] 单引擎任务执行异常: {e}")
        except asyncio.TimeoutError:
            logger.warning(
                f"[Aggregator] 聚合搜索达到全局超时 ({timeout}s)，直接结算已有结果"
            )
        finally:
            # 取消仍在等待的慢任务（例如超时的海外/慢速引擎）
            for t in task_map.keys():
                if not t.done():
                    t.cancel()

        # 使用轻量 BM25 打分重排
        scored_results = self.ranker.rank(query, deduplicated_results)
        final_results = scored_results[:topk]

        logger.info(
            f"[Aggregator] 聚合完成: 原始={total_raw_count} 条, 去重={len(deduplicated_results)} 条, 返回 Top{len(final_results)}"
        )
        return final_results
