"""implement module.

FILENAME    : implement.py
Date        : 2026/08/19 10:58:44
Author      : Huijian Qin
Version     : 1.0.4
Description : 搜索引擎具体实现

Attributes:


Example:
    >>> from implement import
    >>>

"""

import os
import re
import json
import uuid
import asyncio
import urllib
from typing import List, Optional
from bs4 import BeautifulSoup
from curl_cffi import requests
from ddgs import DDGS
from web_search.config.abstract import SearchEngine
from web_search.config.model import SearchResult, UserCredentials
from bilibili_api import select_client
from bilibili_api import search as bili_search
from web_search.config.logging_config import logger
from web_search.server.filter import filtering, is_ad_text

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
        self.url_rss = "https://www.bing.com/search?format=rss"
        self.url = "https://www.bing.com/search?"
        self.session = requests.AsyncSession(impersonate="chrome120")

    async def search(
        self, query: str, topk: int, credentials: Optional[UserCredentials] = None
    ):
        logger.info(f"[BingEngine] 开始搜索: query='{query}', topk={topk}")
        try:
            resp = await self.session.get(
                self.url_rss, params={"q": query}, headers=headers
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
                results = []
                logger.error(f"[BingEngine] 网页版解析发生异常: {e}")
        if not results:
            logger.warning(f"[BingEngine] 未找到关于「{query}」的相关结果")

        logger.info(f"[BingEngine] 成功召回 {len(results)} 条结果")
        return results


class BaiduEngine(SearchEngine):
    def __init__(self):
        super().__init__()
        self.url = "https://wap.baidu.com/s"
        self.session = requests.AsyncSession(impersonate="chrome120")

    async def search(
        self, query: str, topk: int, credentials: Optional[UserCredentials] = None
    ):
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
                ivk_str = article.get("rl-link-data-ivk") if article else None
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
            results = []
            logger.error(f"[BaiduEngine] 网页版解析发生异常: {e}")
        if not results:
            logger.warning(f"[BaiduEngine] 未找到关于「{query}」的相关结果")

        logger.info(f"[BaiduEngine] 成功召回 {len(results)} 条结果")
        return results


class ToutiaoEngine(SearchEngine):
    def __init__(self):
        super().__init__()
        self.url = "https://so.toutiao.com/search"
        self.session = requests.AsyncSession(impersonate="chrome120")

    async def search(
        self, query: str, topk: int, credentials: Optional[UserCredentials] = None
    ):
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
            results = []
            logger.error(f"[ToutiaoEngine] 网页版解析发生异常: {e}")
        if not results:
            logger.warning(f"[ToutiaoEngine] 未找到关于「{query}」的相关结果")

        logger.info(f"[ToutiaoEngine] 成功召回 {len(results)} 条结果")
        return results


class DuckDuckGoEngine(SearchEngine):
    def __init__(self):
        super().__init__()
        self.ddgs = DDGS()

    async def search(
        self, query: str, topk: int, credentials: Optional[UserCredentials] = None
    ):
        logger.info(f"[DuckDuckGoEngine] 开始搜索: query='{query}', topk={topk}")
        results = []
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(self._fetch_sync, query, topk), timeout=8
            )
            results = [
                SearchResult(
                    title=item.get("title"),
                    link=item.get("href"),
                    snippet=item.get("body"),
                    source_engine="DuckDuckGo",
                )
                for item in result
            ]
        except Exception as e:
            results = []
            logger.error(f"DuckDuckGoEngine 搜索底层异常（国内超时）: {str(e)}")
        if not results:
            logger.warning(f"[DuckDuckGoEngine] 未找到关于「{query}」的相关结果")

        logger.info(f"[DuckDuckGoEngine] 成功召回 {len(results)} 条结果")
        return results

    def _fetch_sync(self, query: str, topk: int):
        return list(self.ddgs.text(query, max_results=topk))


class BiliEngine(SearchEngine):
    def __init__(self):
        super().__init__()
        select_client("curl_cffi")

    async def search(
        self, query: str, topk: int, credentials: Optional[UserCredentials] = None
    ):
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
        except Exception as e:
            logger.error(f"BiliEngine 搜索异常: {str(e)}")
        if not results:
            logger.warning(f"[BiliEngine] 未找到关于「{query}」的相关结果")

        logger.info(f"[BiliEngine] 成功召回 {len(results)} 条结果")
        return results


class TavilyEngine(SearchEngine):

    def __init__(self):
        super().__init__()
        self.url = "https://api.tavily.com/search"
        self.session = requests.AsyncSession(impersonate="chrome120")

    async def search(
        self, query: str, topk: int, credentials: Optional[UserCredentials] = None
    ) -> List[SearchResult]:
        logger.info(f"[TavilyEngine] 开始搜索: query='{query}', topk={topk}")
        results = []
        payload = {
            "query": query,
            "max_results": topk,
            "search_depth": "basic",
        }
        req_headers = {
            "Content-Type": "application/json",
            "X-Tavily-Access-Mode": "keyless",
        }
        try:
            resp = await self.session.post(
                self.url,
                headers=req_headers,
                json=payload,
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                for item in data.get("results", []):
                    title = item.get("title", "").strip()
                    link = item.get("url", "").strip()
                    snippet = item.get("content", "").strip()
                    if title and link:
                        results.append(
                            SearchResult(
                                title=title,
                                link=link,
                                snippet=snippet,
                                source_engine="Tavily",
                            )
                        )
        except Exception as e:
            logger.error(f"[TavilyEngine] 搜索异常: {e}")

        if not results:
            logger.warning(f"[TavilyEngine] 未找到关于「{query}」的相关结果")

        logger.info(f"[TavilyEngine] 成功召回 {len(results)} 条结果")
        return results


class DouyinEngine(SearchEngine):
    def __init__(self, fallback_cookie: Optional[str] = None):
        super().__init__()
        self.fallback_cookie = fallback_cookie or os.getenv(
            "DOUYIN_FALLBACK_COOKIE", ""
        )
        self.ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        self.base_headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        self.session = requests.AsyncSession(impersonate="chrome120")

    async def search(
        self,
        query: str,
        topk: int = 10,
        credentials: Optional[UserCredentials] = None,
    ) -> List[SearchResult]:
        logger.info(f"[DouyinEngine] 开始搜索: query='{query}', topk={topk}")
        results = []

        # 1. 获取凭证
        active_cookie = ""
        active_ua = self.ua

        if credentials and credentials.douyin_cookie:
            active_cookie = credentials.douyin_cookie
        elif self.fallback_cookie:
            active_cookie = self.fallback_cookie
        else:
            logger.warning("[DouyinEngine] 未提供抖音 Cookie，跳过搜索")
            return []

        # 2. 动态生成本次请求专属的 aid (UUID)
        session_aid = str(uuid.uuid4())

        encoded_query = urllib.parse.quote(query)

        # 3. 动态组装 Headers，保持 Referer 与会话 aid 一致
        req_headers = self.base_headers.copy()
        req_headers.update(
            {
                "User-Agent": active_ua,
                "Referer": f"https://www.douyin.com/jingxuan/search/{encoded_query}?aid={session_aid}&type=general",
                "Cookie": active_cookie,
            }
        )

        search_api_url = (
            "https://www.douyin.com/aweme/v1/web/general/search/single/?"
            "device_platform=webapp&aid=6383&channel=channel_pc_web&search_channel=aweme_general&"
            "enable_history=1&"
            f"keyword={encoded_query}&"
            "search_source=normal_search&"
            "query_correct_type=1&is_filter_search=0&from_group_id=&disable_rs=0&offset=0&"
            f"count={topk}&"
            "need_filter_settings=0&list_type=single&pc_search_top_1_params=%7B%22enable_ai_search_top_1%22%3A1%7D&"
            "search_id=20260819101514ED3C13A785AF7797E720&update_version_code=170400&pc_client_type=1&"
            "pc_libra_divert=Windows&support_h265=1&support_dash=1&cpu_core_num=16&version_code=190600&"
            "version_name=19.6.0&cookie_enabled=true&screen_width=1707&screen_height=1067&browser_language=zh-CN&"
            "browser_platform=Win32&browser_name=Chrome&browser_version=151.0.0.0&browser_online=true&"
            "engine_name=Blink&engine_version=151.0.0.0&os_name=Windows&os_version=10&device_memory=32&"
            "platform=PC&downlink=6.3&effective_type=4g&round_trip_time=100&webid=7670742409210627594&"
            "uifid=a3682da019905bd2868511de77147b86e5069f1da12659d787063f1c7805c06f5e34a6af80a3b4ca563f763ba3c1554ed0be80718fabbcb852f45952f700a592dcfca90ca325dfaeb397de3f13539ee4b25c8f35ca7574c0f1421fcb20c17cea00b2db40419fa4644877af30f05a2e4e56a292513deb419c1dfd182e4f43b58f6d47c128f97e268cd7892d65f286c63c3c737c806d4d3ba55e2e1686544c6e1b&"
            "a_bogus=EjsjkqywEp5nKd%2Fb8OnYC-pl00oMNsSyFMT%2FS9AleNqZyqUTh8P4%2FNeuaxFFV%2F5NemBTiKI79DU%2FYEncZstwpCHpzmkvuYi6G4%2FCVt8LMZHsGakh7NRBCfbEok4OWuTOmAIRiZJ5lssiIxo5Iq9TAB5SK%2F-r-cRDOZ3JVIzSx29m0AWjwx2naVbZThiq7j%3D%3D&"
            "verifyFp=verify_msgwpltt_CrWPVoNw_jtcC_4nkC_AVYm_Wv94JG8fmHK7&"
            "fp=verify_msgwpltt_CrWPVoNw_jtcC_4nkC_AVYm_Wv94JG8fmHK7"
        )

        try:
            resp = await self.session.get(
                search_api_url,
                headers=req_headers,
                timeout=8,
            )

            if resp.status_code != 200:
                logger.warning(f"[DouyinEngine] 请求失败，状态码: {resp.status_code}")
                return results

            if not resp.text or not resp.text.strip():
                logger.warning(
                    "[DouyinEngine] 接口返回空，Cookie 可能已失效或被风控限制"
                )
                return results

            data = resp.json()
            data_list = data.get("data", [])

            for item in data_list:
                if len(results) >= topk:
                    break

                aweme_info = item.get("aweme_info")
                if not aweme_info:
                    continue

                title = aweme_info.get("desc", "").strip()
                aweme_id = aweme_info.get("aweme_id", "")
                video_link = (
                    f"https://www.douyin.com/video/{aweme_id}" if aweme_id else ""
                )

                url_list = (
                    aweme_info.get("video", {}).get("play_addr", {}).get("url_list", [])
                )
                video_url = url_list[-1] if url_list else None

                if title or video_link:
                    results.append(
                        SearchResult(
                            title=title or f"抖音视频_{aweme_id}",
                            link=video_link,
                            snippet=title,
                            source_engine="Douyin",
                            video_url=video_url,
                        )
                    )

        except Exception as e:
            logger.error(f"[DouyinEngine] 抓取解析异常: {e}")
            results = []

        logger.info(f"[DouyinEngine] 成功召回 {len(results)} 条结果")
        return results


class GithubEngine(SearchEngine):
    """基于 GitHub 官方 REST API 的开源仓库搜索引擎
    具备关键词清洗、多词降级、SSL容错与标准 SearchResult 封装
    """

    def __init__(self):
        super().__init__()
        self.api_url = "https://api.github.com/search/repositories"
        self.headers = {
            "User-Agent": "bigOClaw-web-search",
            "Accept": "application/vnd.github+json",
        }
        # 使用 curl_cffi 异步会话，自带 TLS/SSL 兼容性
        self.session = requests.AsyncSession(impersonate="chrome120")

    async def _fetch_api(self, q: str, topk: int) -> list:
        """底层异步请求，带 SSL 容错"""
        params = {"q": q, "per_page": topk}
        try:
            resp = await self.session.get(
                self.api_url,
                params=params,
                headers=self.headers,
                timeout=12,
                verify=True,
            )
        except Exception as e:
            # 捕获 SSL 错误并降级重试
            if "certificate" in str(e).lower() or "ssl" in str(e).lower():
                resp = await self.session.get(
                    self.api_url,
                    params=params,
                    headers=self.headers,
                    timeout=12,
                    verify=False,
                )
            else:
                raise e

        if resp.status_code == 403:
            logger.warning("[GithubEngine] GitHub API 速率限制 (403 Rate Limit)")
            return []
        if resp.status_code != 200:
            logger.error(f"[GithubEngine] 请求失败 HTTP {resp.status_code}")
            return []

        return resp.json().get("items", [])

    async def search(
        self, query: str, topk: int, credentials: Optional[UserCredentials] = None
    ) -> List[SearchResult]:
        logger.info(f"[GithubEngine] 开始搜索: query='{query}', topk={topk}")
        results = []

        # 1. 净化 query，剔除 github.com / github 等冗余词
        clean_q = re.sub(r"github\.com|github", " ", query, flags=re.IGNORECASE)
        clean_q = re.sub(r"\s+", " ", clean_q).strip() or query

        try:
            items = await self._fetch_api(clean_q, topk)

            # 2. 降级重试策略：多词查询无结果时，尝试只搜第一个关键词
            if not items and len(clean_q.split()) > 1:
                first_term = clean_q.split()[0]
                logger.debug(
                    f"[GithubEngine] 多词检索命中为空，降级单词重试: '{first_term}'"
                )
                items = await self._fetch_api(first_term, topk)

            # 3. 解析并组装为系统的 SearchResult
            for item in items:
                if len(results) >= topk:
                    break
                name = item.get("full_name", "")
                stars = item.get("stargazers_count") or 0
                lang = item.get("language") or ""
                desc = (item.get("description") or "").strip()
                repo_url = item.get("html_url", "")

                meta_parts = []
                if stars:
                    meta_parts.append(f"⭐{stars}")
                if lang:
                    meta_parts.append(f"[{lang}]")
                meta_str = f" {' '.join(meta_parts)}" if meta_parts else ""

                title = f"{name}{meta_str}"
                snippet = desc if desc else f"GitHub repository for {name}"

                if name and repo_url:
                    results.append(
                        SearchResult(
                            title=title,
                            link=repo_url,
                            snippet=snippet,
                            source_engine="GitHub",
                            video_url="",
                        )
                    )

        except Exception as e:
            logger.error(f"[GithubEngine] 搜索异常: {e}")

        if not results:
            logger.warning(f"[GithubEngine] 未找到关于「{query}」的仓库")

        logger.info(f"[GithubEngine] 成功召回 {len(results)} 条结果")
        return results


if __name__ == "__main__":

    s = TavilyEngine()
    result = asyncio.run(s.search("大模型", 3))
    print(result)
