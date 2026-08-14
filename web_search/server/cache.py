"""cache module.

FILENAME    : cache.py
Date        : 2026/08/14 12:14:09
Author      : Huijian Qin
Version     : 1.0.0
Description : Redis 缓存层实现，保护真实请求并提供 Query 级别的搜索结果缓存

Attributes:


Example:
    >>> from cache import
    >>>

"""

import json
import re
import hashlib
from typing import List, Optional
import redis.asyncio as redis
from config.model import SearchResult
from config.logging_config import logger


class SearchCache:
    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: Optional[str] = None,
        ttl: int = 3600,  # 默认缓存 1 小时
    ):
        self.ttl = ttl
        self.redis_client = redis.Redis(
            host=host,
            port=port,
            db=db,
            password=password,
            decode_responses=True,
        )

    @staticmethod
    def _normalize_query(query: str) -> str:
        """
        轻量级文本归一化处理
        1. 转小写
        2. 剔除常见中英文标点符号
        3. 合并连续空白字符
        """
        # 转小写
        q = query.lower().strip()
        # 剔除中英文标点符号
        q = re.sub(r"[^\w\s\u4e00-\u9fa5]", "", q)
        # 合并多个连续空格为单空格
        q = re.sub(r"\s+", " ", q)
        return q

    @staticmethod
    def _align_topk(topk: int) -> int:
        """
        TopK 粒度向上对齐
        例如：topk=1..5 统一归一化为 5；topk=6..10 统一归一化为 10
        """
        if topk <= 5:
            return 5
        if topk <= 10:
            return 10
        if topk <= 20:
            return 20
        # 大于 20 的按 10 向上取整
        return ((topk + 9) // 10) * 10

    def _gen_key(self, query: str, topk: int) -> str:
        """
        优化后的高效缓存 Key 生成逻辑
        例如:
        - "Python 异步编程?" (topk=3) -> search_cache:f0e2a3b1c4d5:5
        - "python   异步编程" (topk=5) -> search_cache:f0e2a3b1c4d5:5 (完全击穿复用)
        """
        normalized_q = self._normalize_query(query)

        # 取 MD5 前 16 位 Hex（足够低碰撞率，且占用 Redis 内存极小）
        q_hash = hashlib.md5(normalized_q.encode("utf-8")).hexdigest()[:16]

        aligned_topk = self._align_topk(topk)

        return f"search_cache:{q_hash}:{aligned_topk}"

    async def get(self, query: str, topk: int) -> Optional[List[SearchResult]]:
        """从 Redis 获取缓存的 SearchResult 列表"""
        key = self._gen_key(query, topk)
        try:
            cached_data = await self.redis_client.get(key)
            if cached_data:
                logger.info(f"[RedisCache] 命中缓存: query='{query}'")
                items = json.loads(cached_data)
                return [SearchResult(**item) for item in items]
        except Exception as e:
            logger.error(f"[RedisCache] 读取缓存失败: {e}")
        return None

    async def set(self, query: str, topk: int, results: List[SearchResult]) -> None:
        """将 SearchResult 列表序列化并写入 Redis"""
        if not results:
            return
        key = self._gen_key(query, topk)
        try:
            # dataclass 转换为 dict 结构存储
            data_to_cache = [
                {
                    "title": item.title,
                    "link": item.link,
                    "snippet": item.snippet,
                    "source_engine": item.source_engine,
                    "is_ad": item.is_ad,
                }
                for item in results
            ]
            await self.redis_client.setex(
                key, self.ttl, json.dumps(data_to_cache, ensure_ascii=False)
            )
            logger.info(f"[RedisCache] 写入缓存成功: query='{query}', ttl={self.ttl}s")
        except Exception as e:
            logger.error(f"[RedisCache] 写入缓存失败: {e}")

    async def close(self):
        await self.redis_client.close()
