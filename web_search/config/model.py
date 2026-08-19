"""model module.

FILENAME    : model.py
Date        : 2026/08/19 10:58:25
Author      : Huijian Qin
Version     : 1.0.1
Description : 定义网络搜索结果

Attributes:


Example:
    >>> from model import
    >>>

"""

from dataclasses import dataclass, field


@dataclass
class SearchResult:
    title: str = ""
    link: str = ""
    snippet: str = ""
    source_engine: str = ""
    video_url: str = ""
    is_ad: bool = False  # 预留
