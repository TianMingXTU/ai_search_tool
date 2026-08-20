"""
FILENAME    : filter.py
Date        : 2026/08/14 16:20:00
Author      : Huijian Qin
Version     : 1.0.2
Description : 采用语言感知策略与智能分词过滤广告及不相干网页，完美支持中英文及混合搜索
"""

import re
import jieba
import jieba.posseg as pseg

jieba.initialize()
# 中文停用词表
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

# 英文专属停用词表
ENGLISH_STOPWORDS = {
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
    "was",
    "were",
    "be",
    "been",
    "with",
    "as",
    "by",
    "at",
    "from",
    "it",
    "this",
    "that",
    "which",
    "how",
    "what",
    "where",
    "when",
    "why",
    "who",
}

# 中文允许保留的词性：名词(n)、动词(v)、形容词(a)、英文(eng)、数字(m)、专有名词(nz)、成语/习用语(i/l)
ALLOWED_POS = ("n", "v", "a", "eng", "m", "nz", "i", "l")

AD_KEYWORDS = {"广告", "商业推广", "赞助", "Promoted", "Ad"}


def _is_chinese(text: str) -> bool:
    """判断文本中是否包含中文字符"""
    return bool(re.search(r"[\u4e00-\u9fa5]", text))


def _extract_english_keywords(text: str) -> set[str]:
    """英文专用分词与关键词提取：正则提取单词 + 转小写 + 去停用词"""
    words = re.findall(r"\b[a-zA-Z0-9_-]+\b", text.lower())
    return {w for w in words if w not in ENGLISH_STOPWORDS and len(w) > 1}


def extract_keywords(text: str) -> set[str]:
    """
    从中文/中英混合文本中提取核心关键词 (基于 jieba 分词)
    """
    words = []
    text_clean = text.lower()

    for word, flag in pseg.lcut(text_clean):
        word = word.strip()
        if not word or word in STOPWORDS:
            continue

        if flag.startswith(ALLOWED_POS):
            words.append(word)

    return set(words)


def filtering(query: str, title: str, threshold: float = 0.3) -> bool:
    """
    相关性校验：根据 Query 语言类型自动切换过滤策略，彻底解决英文被 jieba 误杀的问题

    :param query: 搜索关键词
    :param title: 搜索结果网页标题
    :param threshold: 关键词命中率阈值 (默认命中 30% 以上即算相关)
    :return: bool 是否保留该结果
    """
    if not query or not title:
        return False

    # -------------------------------------------------------------
    # 策略 A：纯英文 / 无中文场景，采用原生英文正则分词
    # -------------------------------------------------------------
    if not _is_chinese(query):
        q_en_keywords = _extract_english_keywords(query)

        # 兜底：若提不出有效英文单词（如 Query 全是符号），降级为简单的单词子串包含
        if not q_en_keywords:
            tokens = [t.lower() for t in re.split(r"\s+", query) if t.strip()]
            if not tokens:
                return True
            return any(token in title.lower() for token in tokens)

        t_en_keywords = _extract_english_keywords(title)
        intersection = q_en_keywords & t_en_keywords

        # 满足命中率比例放行
        hit_ratio = (
            len(intersection) / len(q_en_keywords) if len(q_en_keywords) > 0 else 0
        )
        if hit_ratio >= threshold:
            return True

        # 子串降级包含：长单词在标题中直接命中也判定为相关
        title_lower = title.lower()
        return any(kw in title_lower for kw in q_en_keywords if len(kw) >= 3)

    # -------------------------------------------------------------
    # 策略 B：中文 / 中英混合场景，采用 jieba 词性标注分词
    # -------------------------------------------------------------
    q_keywords = extract_keywords(query)
    t_keywords = extract_keywords(title)

    # 兜底逻辑 1：Query 提不出符合指定词性的关键词
    if not q_keywords:
        tokens = [t.lower() for t in re.split(r"\s+", query) if t.strip()]
        if not tokens:
            return True
        return any(token in title.lower() for token in tokens)

    intersection = q_keywords & t_keywords
    hit_ratio = len(intersection) / len(q_keywords) if len(q_keywords) > 0 else 0

    if hit_ratio >= threshold:
        return True

    # 兜底逻辑 2：英文/数字短词直接子串匹配
    title_lower = title.lower()
    for kw in q_keywords:
        if len(kw) >= 3 and kw in title_lower:
            return True

    return False


def is_ad_text(text: str) -> bool:
    """判定文本中是否显式带有广告标识"""
    if not text:
        return False
    text_clean = text.strip()
    return text_clean in AD_KEYWORDS or any(kw in text_clean for kw in AD_KEYWORDS)


# if __name__ == "__main__":
#     print("=" * 60)
#     print(" 运行 filter.py 单元过滤逻辑测试")
#     print("=" * 60)

#     test_cases = [
#         # --- 1. 英文场景测试 (验证英文是否被误杀) ---
#         (
#             "python asyncio tutorial",
#             "Python Asyncio Complete Guide and Tutorial for Beginners",
#             True,
#             "英文相关标题 (高命中)",
#         ),
#         (
#             "python asyncio tutorial",
#             "How to install Java on Ubuntu Linux 22.04",
#             False,
#             "英文无关标题 (无命中)",
#         ),
#         (
#             "how to use docker-compose",
#             "A step-by-step guide on docker-compose orchestration",
#             True,
#             "英文带连字符专业词",
#         ),
#         # --- 2. 中文场景测试 ---
#         (
#             "人工智能 深度学习",
#             "2026年最新人工智能与深度学习实战指南",
#             True,
#             "中文相关标题",
#         ),
#         (
#             "人工智能 深度学习",
#             "今日猪肉价格行情与养殖业最新动态",
#             False,
#             "中文无关标题",
#         ),
#         # --- 3. 中英混合场景测试 ---
#         (
#             "LangChain 智能体开发",
#             "基于 LangChain 快速搭建大模型 Multi-Agent 架构",
#             True,
#             "中英混合相关标题",
#         ),
#         (
#             "LangChain 智能体开发",
#             "零基础教你做一顿丰盛的红烧肉",
#             False,
#             "中英混合无关标题",
#         ),
#         # --- 4. 边界防御测试 ---
#         ("!!!", "Python Complete Tutorial", True, "Query 仅包含符号 (兜底放行)"),
#         ("", "Any Title", False, "Query 为空"),
#         ("Python", "", False, "Title 为空"),
#     ]

#     for idx, (q, t, expected, desc) in enumerate(test_cases, 1):
#         actual = filtering(q, t)
#         status = "PASSED" if actual == expected else "FAILED"
#         print(f"[{status}] Case {idx}: {desc}")
#         print(f"   Query : '{q}'")
#         print(f"   Title : '{t}'")
#         print(f"   Result: {actual} (Expected: {expected})\n")

#     print("-" * 60)
#     print(" 广告判定测试:")
#     print(f"  '商业推广' -> is_ad: {is_ad_text('商业推广')}")
#     print(f"  'Promoted' -> is_ad: {is_ad_text('Promoted')}")
#     print(f"  '普通技术文章' -> is_ad: {is_ad_text('普通技术文章')}")
#     print("=" * 60)
