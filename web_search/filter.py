"""
FILENAME    : filter.py
Date        : 2026/08/11 16:34:43
Author      : Huijian Qin
Version     : 1.0.1
Description : 采用分词规则与子串匹配结合过滤广告以及不相干网页，完美支持中英文混合搜索
"""

import re
import jieba.posseg as pseg

# 扩展常用停用词表
STOPWORDS = {
    "的",
    "了",
    "是",
    "在",
    "和",
    "与",
    "或",
    "等",
    "有",
    "用",
    "这",
    "那",
    "a",
    "an",
    "the",
    "in",
    "on",
    "of",
    "for",
    "to",
    "and",
    "or",
    "is",
    "are",
}

# 允许保留的词性：名词(n)、动词(v)、形容词(a)、英文(eng)、数字(m)、专有名词(nz)、成语/习用语(i/l)
ALLOWED_POS = ("n", "v", "a", "eng", "m", "nz", "i", "l")


def extract_keywords(text: str) -> set[str]:
    """
    从文本中提取核心关键词，支持中英文、数字及常见专有名词
    """
    words = []
    text_clean = text.lower()

    for word, flag in pseg.lcut(text_clean):
        word = word.strip()
        if not word or word in STOPWORDS:
            continue

        # 只要符合指定的词性前缀，即视为有效关键词
        if flag.startswith(ALLOWED_POS):
            words.append(word)

    return set(words)


def filtering(query: str, title: str, threshold: float = 0.3) -> bool:
    """
    相关性校验：判断 title 是否与 query 具备足够的相关度

    :param query: 搜索关键词
    :param title: 搜索结果网页标题
    :param threshold: 关键词命中率阈值 (默认命中 30% 以上即算相关)
    :return: bool 是否保留该结果
    """
    if not query or not title:
        return False

    q_keywords = extract_keywords(query)
    t_keywords = extract_keywords(title)

    # --- 兜底逻辑 1：如果 Query 提不出任何有效词性关键词 ---
    if not q_keywords:
        tokens = [t.lower() for t in re.split(r"\s+", query) if t.strip()]
        if not tokens:
            return True
        return any(token in title.lower() for token in tokens)

    intersection = q_keywords & t_keywords

    hit_ratio = len(intersection) / len(q_keywords)

    if hit_ratio >= threshold:
        return True

    # --- 兜底逻辑 2：英文/数字短词直接子串匹配 ---
    title_lower = title.lower()
    for kw in q_keywords:
        if len(kw) >= 3 and kw in title_lower:
            return True

    return False


AD_KEYWORDS = {"广告", "商业推广", "赞助", "Promoted", "Ad"}


def is_ad_text(text: str) -> bool:
    """判定文本中是否显式带有广告标识"""
    if not text:
        return False
    text_clean = text.strip()
    return text_clean in AD_KEYWORDS or any(kw in text_clean for kw in AD_KEYWORDS)
