"""implement module.

FILENAME    : implement.py
Date        : 2026/08/14 10:16:32
Author      : Huijian Qin
Version     : 1.0.1
Description : 搜索引擎具体实现

Attributes:


Example:
    >>> from implement import
    >>>

"""

import json
import asyncio
from bs4 import BeautifulSoup
from curl_cffi import requests
from ddgs import DDGS
from abstract import SearchEngine
from model import SearchResult
from filter import filtering
from bilibili_api import select_client
from bilibili_api import search as bili_search
from logging_config import logger
from filter import filtering, is_ad_text

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
        self.url = "https://www.bing.com/search?format=rss"
        self.session = requests.AsyncSession(impersonate="chrome120")

    async def search(self, query: str, topk: int):
        logger.info(f"[BingEngine] 开始搜索: query='{query}', topk={topk}")
        try:
            resp = await self.session.get(
                self.url, params={"q": query}, headers=headers
            )
            results = []
            if resp.status_code != 200:
                return results
            soup = BeautifulSoup(resp.text, "lxml-xml")
            for item in soup.find_all("item"):
                if len(results) >= topk:
                    break
                title_el = item.find("title")
                link_el = item.find("link")
                desc_el = item.find("description")
                title = title_el.get_text(strip=True) if title_el else ""
                link = link_el.get_text(strip=True) if link_el else ""
                snippet = desc_el.get_text(strip=True) if desc_el else ""
                if title and link and snippet and filtering(query, title):
                    res = SearchResult(
                        title=title, link=link, snippet=snippet, source_engine="Bing"
                    )
                    results.append(res)
        except Exception:
            results = []

        if not results:
            try:
                self.url = "https://www.bing.com/search?"
                resp = await self.session.get(
                    self.url, params={"q": query}, headers=headers
                )
                results = []
                if resp.status_code != 200:
                    return results
                soup = BeautifulSoup(resp.text, "lxml")

                # 剔除顶部的 b_ad 广告块
                for ad_block in soup.select(".b_ad, .b_adCard"):
                    ad_block.decompose()

                for item in soup.select(".b_algo"):
                    if len(results) >= topk:
                        break
                    # 判断子元素中是否带广告标签
                    if item.select_one(".b_ad") or item.select_one(".b_adLabel"):
                        continue
                    tag_a = item.select_one("h2 > a")
                    title = tag_a.get_text(strip=True) if tag_a else ""
                    link = tag_a.get("href") if tag_a else ""
                    snippet_elem = item.select_one("div.b_caption")
                    snippet = snippet_elem.get_text(strip=True)
                    if title and link and filtering(query, title):
                        # if title:
                        res = SearchResult(
                            title=title,
                            link=link,
                            snippet=snippet,
                            source_engine="Bing",
                        )
                        results.append(res)
            except Exception as e:
                logger.error(f"[BingEngine] 网页版解析发生异常: {e}")
        if not results:
            logger.warning(f"[BingEngine] 未找到关于「{query}」的相关结果")
            return f"未搜索到关于「{query}」的相关结果，请尝试更换关键词。"

        logger.info(f"[BingEngine] 成功召回 {len(results)} 条结果")
        return results


class BaiduEngine(SearchEngine):
    def __init__(self):
        super().__init__()
        self.url = "https://wap.baidu.com/s"
        self.session = requests.AsyncSession(impersonate="chrome120")

    async def search(self, query: str, topk: int):
        logger.info(f"[BaiduEngine] 开始搜索: query='{query}', topk={topk}")
        try:
            resp = await self.session.get(
                self.url, params={"word": query}, headers=headers
            )
            results = []
            if resp.status_code != 200:
                return results
            soup = BeautifulSoup(resp.text, "lxml")
            for item in soup.select(".c-result.result"):
                if len(results) >= topk:
                    break

                # --- 百度广告精准判定逻辑 ---
                # 1. 检查 item 的 class 列表中是否包含广告标识
                item_classes = item.get("class", [])
                if any(
                    cls in item_classes
                    for cls in ["ec_ad_results", "ec_res_ent", "ec_ad"]
                ):
                    logger.debug("[BaiduEngine] 命中 Class 广告卡片，已跳过")
                    continue

                # 2. 检查节点内是否存在“广告”文本标记或专属样式属性
                ad_badge = item.select_one(".cos-color-text-tiny") or item.select_one(
                    ".c-color-gray"
                )
                if ad_badge and is_ad_text(ad_badge.get_text()):
                    logger.debug("[BaiduEngine] 命中文字广告标识，已跳过")
                    continue

                # 3. 检查特定 dataset 属性
                if item.get("data-ecimid") or item.get("ec-data"):
                    logger.debug("[BaiduEngine] 命中 data-ecimid 属性广告，已跳过")
                    continue

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
                    results.append(res)
        except Exception as e:
            logger.error(f"[BaiduEngine] 网页版解析发生异常: {e}")
        if not results:
            logger.warning(f"[BaiduEngine] 未找到关于「{query}」的相关结果")
            return f"未搜索到关于「{query}」的相关结果，请尝试更换关键词。"

        logger.info(f"[BaiduEngine] 成功召回 {len(results)} 条结果")
        return results


class ToutiaoEngine(SearchEngine):
    def __init__(self):
        super().__init__()
        self.url = "https://so.toutiao.com/search"
        self.session = requests.AsyncSession(impersonate="chrome120")

    async def search(self, query: str, topk: int):
        logger.info(f"[ToutiaoEngine] 开始搜索: query='{query}', topk={topk}")
        try:
            resp = await self.session.get(
                self.url,
                params={"keyword": query, "dvpf": "pc", "source": "input"},
                headers=headers,
            )
            results = []
            if resp.status_code != 200:
                return results
            soup = BeautifulSoup(resp.text, "lxml")
            for item in soup.find_all("div", class_="result-content"):
                if len(results) >= topk:
                    break

                # --- 头条广告过滤 ---
                ad_span = item.find("span", text="广告") or item.select_one(".ad-tag")
                if ad_span:
                    logger.debug("[ToutiaoEngine] 命中头条广告，已跳过")
                    continue

                tag_a = item.find("a")
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
        except Exception as e:
            logger.error(f"[ToutiaoEngine] 网页版解析发生异常: {e}")
        if not results:
            logger.warning(f"[ToutiaoEngine] 未找到关于「{query}」的相关结果")
            return f"未搜索到关于「{query}」的相关结果，请尝试更换关键词。"

        logger.info(f"[ToutiaoEngine] 成功召回 {len(results)} 条结果")
        return results


class DuckDuckGoEngine(SearchEngine):
    def __init__(self):
        super().__init__()

    async def search(self, query: str, topk: int):
        logger.info(f"[DuckDuckGoEngine] 开始搜索: query='{query}', topk={topk}")
        try:
            with DDGS() as ddgs:
                result = await asyncio.to_thread(self._fetch_sync, query, topk)
                results = [
                    SearchResult(
                        title=item.get("title"),
                        link=item.get("href"),
                        snippet=item.get("body"),
                        source_engine="DuckDuckGo",
                    )
                    for item in result
                ]
            if not results:
                logger.warning(f"[ToutiaoEngine] 未找到关于「{query}」的相关结果")
                return f"未搜索到关于「{query}」的相关结果，请尝试更换关键词。"

            logger.info(f"[ToutiaoEngine] 成功召回 {len(results)} 条结果")
            return results
        except Exception as e:
            raise RuntimeError(f"DuckDuckGo 搜索底层异常: {str(e)}")

    def _fetch_sync(self, query: str, topk: int):
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=topk))


class BiliEngine(SearchEngine):
    def __init__(self):
        super().__init__()
        select_client("curl_cffi")

    async def search(self, query: str, topk: int):
        logger.info(f"[BiliEngine] 开始搜索: query='{query}', topk={topk}")
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
            if not results:
                logger.warning(f"[BiliEngine] 未找到关于「{query}」的相关结果")
                return f"未搜索到关于「{query}」的相关结果，请尝试更换关键词。"

            logger.info(f"[BiliEngine] 成功召回 {len(results)} 条结果")
            return results
        except Exception as e:
            raise RuntimeError(f"BiliEngine 搜索异常: {str(e)}")


if __name__ == "__main__":

    s = BingEngine()
    result = asyncio.run(s.search("广州", 3))
    print(result)
