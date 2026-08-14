"""abstract module.

FILENAME    : abstract.py
Date        : 2026/08/09 21:00:08
Author      : Huijian Qin
Version     : 1.0.0
Description : 搜索引擎抽象类的定义

Attributes:


Example:
    >>> from abstract import SearchEngine
    >>>

"""

from typing import List
from abc import ABC, abstractmethod
from config.model import SearchResult


class SearchEngine(ABC):
    @abstractmethod
    async def search(self, query: str, topk: int) -> List[SearchResult]:
        """search

        Args:
            query (str): 搜索关键字
            topk (int): 返回结果数量

        Returns:
            List[SearchResult]: SearchResult
        """
        pass
