"""model module.

FILENAME    : model.py
Date        : 2026/08/09 20:54:41
Author      : Huijian Qin
Version     : 1.0.0
Description : 定义网络搜索结果

Attributes:


Example:
    >>> from model import
    >>>

"""

from dataclasses import dataclass, field


@dataclass
class SearchResult:
    title: str
    link: str
    snippet: str
    source_engine: str
    is_ad: bool = False  # 预留
