"""filter module.

FILENAME    : filter.py
Date        : 2026/08/10 16:34:43
Author      : Huijian Qin
Version     : 1.0.0
Description : 采用分词规则过滤广告以及不相干网页

Attributes:


Example:
    >>> from filter import
    >>>

"""

import jieba.posseg as pseg


def filtering(query: str, title: str):
    stopwords = set(["的", "了", "是", "在", "和", "与", "或", "等"])

    def extract_keywords(text):
        words = []
        for word, flag in pseg.lcut(text):
            if flag.startswith(("n", "v", "a")) and word not in stopwords:
                words.append(word)
        return set(words)

    return bool(extract_keywords(query) & extract_keywords(title))
