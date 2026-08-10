"""implement module.

FILENAME    : implement.py
Date        : 2026/08/09 21:03:54
Author      : Huijian Qin
Version     : 1.0.0
Description : 搜索引擎具体实现

Attributes:


Example:
    >>> from implement import BingEngine
    >>> BingEngine().search(query,topk)

"""

import json
from bs4 import BeautifulSoup
from curl_cffi import requests
from ddgs import DDGS
from abstract import SearchEngine
from model import SearchResult
from filter import filtering
from bilibili_api import select_client
from bilibili_api import search as bili_search

headers = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://wap.baidu.com/",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Dest": "document",
}


class BingEngine(SearchEngine):
    def __init__(self):
        super().__init__()
        self.url = "https://www.bing.com/search"
        self.session = requests.AsyncSession(impersonate="chrome120")

    async def search(self, query: str, topk: int):
        resp = await self.session.get(self.url, params={"q": query}, headers=headers)
        results = []
        if resp.status_code != 200:
            return results
        soup = BeautifulSoup(resp.text, "lxml")
        for item in soup.select(".b_algo"):
            if len(results) >= topk:
                break
            tag_a = item.select_one("h2 > a")
            title = tag_a.get_text(strip=True) if tag_a else ""
            link = tag_a.get("href") if tag_a else ""
            snippet_elem = item.select_one("div.b_caption")
            snippet = snippet_elem.get_text(strip=True)
            if title and link and snippet and filtering(query, title):
                res = SearchResult(
                    title=title, link=link, snippet=snippet, source_engine="Bing"
                )
                results.append(res)
        return results


class BaiduEngine(SearchEngine):
    def __init__(self):
        super().__init__()
        self.url = "https://wap.baidu.com/s"
        self.session = requests.AsyncSession(impersonate="chrome120")

    async def search(self, query: str, topk: int):
        resp = await self.session.get(self.url, params={"word": query}, headers=headers)
        results = []
        if resp.status_code != 200:
            return results
        soup = BeautifulSoup(resp.text, "lxml")
        for item in soup.select(".c-result.result"):
            if len(results) >= topk:
                break
            title_elem = item.select_one("h3.cosc-title")
            title = title_elem.get_text(strip=True) if title_elem else ""
            # 获取链接
            article = item.find("article")
            ivk_str = article.get("rl-link-data-ivk")
            ivk_data = json.loads(ivk_str) if ivk_str else {}
            link = ivk_data.get("control", {}).get("dataUrl")
            snippet_elem = item.find(
                "div", class_="cos-color-text-tiny summary-gap_68jXq"
            )
            snippet = snippet_elem.get_text(strip=True) if snippet_elem else ""
            if title and link and snippet and filtering(query, title):
                res = SearchResult(
                    title=title, link=link, snippet=snippet, source_engine="Baidu"
                )
                # TODO 实现广告判断和解析
                results.append(res)
        return results


class ToutiaoEngine(SearchEngine):
    def __init__(self):
        super().__init__()
        self.url = "https://so.toutiao.com/search"
        self.session = requests.AsyncSession(impersonate="chrome120")

    async def search(self, query: str, topk: int):
        resp = await self.session.get(
            self.url,
            params={"keyword": query, "dvpf": "pc", "source": "input"},
            headers=headers,
        )
        results = []
        if resp.status_code != 200:
            return results
        soup = BeautifulSoup(resp.text, "lxml")
        # print(soup.select("div.result-content"))
        for item in soup.find_all("div", class_="result-content"):
            if len(results) >= topk:
                break

            tag_a = item.find("a")
            # print(tag_a)
            title = tag_a.get_text() if tag_a else ""
            link = tag_a.get("href") if tag_a else ""

            snippet_elem = item.find(
                "div", class_="flex-1 text-default text-m text-regular"
            )
            snippet = snippet_elem.get_text(strip=True) if snippet_elem else ""
            if title and link and snippet and filtering(query, title):
                res = SearchResult(
                    title=title, link=link, snippet=snippet, source_engine="Toutiao"
                )
                results.append(res)
        return results


class DuckDuckGoEngine(SearchEngine):
    def __init__(self):
        super().__init__()

    async def search(self, query: str, topk: int):
        try:
            with DDGS() as ddgs:
                result = list(ddgs.text(query, max_results=topk))
                result = [
                    SearchResult(
                        title=item.get("title"),
                        link=item.get("href"),
                        snippet=item.get("body"),
                        source_engine="DuckDuckGo",
                    )
                    for item in result
                ]
                return result
        except Exception as e:
            raise RuntimeError(f"DuckDuckGo 搜索底层异常: {str(e)}")


class BiliEngine(SearchEngine):
    def __init__(self):
        super().__init__()
        select_client("curl_cffi")

    async def search(self, query: str, topk: int):
        try:
            results = []
            data = await bili_search.search_by_type(
                keyword=query,
                search_type=bili_search.SearchObjectType.VIDEO,
                # order_type=bili_search.OrderVideo.TOTALRANK,
                page=1,
                page_size=topk,
            )
            items = data.get("result", [])
            for item in items:
                bvid = str(item.get("bvid") or "").strip()
                title = str(item.get("title") or "")
                url = f"https://www.bilibili.com/video/{bvid}"
                snippet = str(item.get("description") or "")
                res = SearchResult(
                    title=title,
                    link=url,
                    snippet=snippet,
                    source_engine="BiliBili",
                )
                results.append(res)
            return results
        except Exception as e:
            raise RuntimeError(f"BiliEngine 搜索异常: {str(e)}")


if __name__ == "__main__":
    import asyncio

    s = BiliEngine()
    result = asyncio.run(s.search("人工智能", 3))
    print(result)
