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

import re
import json
import asyncio
import urllib
from typing import List
from bs4 import BeautifulSoup
from curl_cffi import requests
from ddgs import DDGS
from web_search.config.abstract import SearchEngine
from web_search.config.model import SearchResult
from web_search.server.filter import filtering
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

    async def search(self, query: str, topk: int):
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

    async def search(self, query: str, topk: int):
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

    async def search(self, query: str, topk: int) -> List[SearchResult]:
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

    def __init__(self):
        super().__init__()
        # 与抓包请求参数中的 Chrome/151 及 Windows 环境对齐
        self.ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        self.session = requests.AsyncSession(impersonate="chrome120")

        self.headers = {
            "User-Agent": self.ua,
            "Referer": "https://www.douyin.com/search/%E4%BA%BA%E5%B7%A5%E6%99%BA%E8%83%BD?aid=5919da1d-73e9-4c14-9936-38377560f456&type=general",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            # 粘贴你在抓包该请求时所带的最新 Cookie
            "Cookie": "enter_pc_once=1; UIFID_TEMP=a3682da019905bd2868511de77147b86e5069f1da12659d787063f1c7805c06f414538dcaf98d20b77b7235c3a61005e3f4a9c5f90c8d238227831362c2dde180c105dc487a3da34ce791969d8e2ced6; s_v_web_id=verify_msgwpltt_CrWPVoNw_jtcC_4nkC_AVYm_Wv94JG8fmHK7; hevc_supported=true; fpk1=U2FsdGVkX1+UfvBxvYIxhiP44CiWt+GElI5MARrI41siCzvKIrM3g36Cw0qfVAz0ax5eCi1Is2PwG+3/2WCdgA==; fpk2=6967ec7261b3cbe6a91d798c6b951c60; passport_csrf_token=f8f91a970fc2acb53f27ad262f79da88; passport_csrf_token_default=f8f91a970fc2acb53f27ad262f79da88; bd_ticket_guard_regenerate_keys_time=2026-08-06/10:39:11; bd_ticket_guard_client_web_domain=2; SEARCH_UN_LOGIN_PV_CURR_DAY=%7B%22date%22%3A1785983981085%2C%22count%22%3A2%7D; UIFID=a3682da019905bd2868511de77147b86e5069f1da12659d787063f1c7805c06f5e34a6af80a3b4ca563f763ba3c1554ed0be80718fabbcb852f45952f700a592dcfca90ca325dfaeb397de3f13539ee4b25c8f35ca7574c0f1421fcb20c17cea00b2db40419fa4644877af30f05a2e4e56a292513deb419c1dfd182e4f43b58f6d47c128f97e268cd7892d65f286c63c3c737c806d4d3ba55e2e1686544c6e1b; passport_mfa_token=Cjcoaau8QBPRMGkpkcy4v%2FVU2Mo2BzmDxISOWunYHy0yXJBhHIzWer5hvWzZRcc6vpmrHvWf%2F0fOGkoKPAAAAAAAAAAAAABQvw%2FZa0rVteuwzoCmIiRvDJxPzR9quPNR9sq3Re3fp9HxMI7nVLC05nHrcUSIQ99o%2FRCR6pgOGPax0WwgAiIBAyZuFTw%3D; d_ticket=57242966c51d4e99cdfca89192586222a88ad; passport_assist_user=CkFPdljNG4RCvi8W6h8LFbJL1J3gM-Hx53KrfQPxylXtBSLNW991dJ0mIWYrkG1lwycaplxHaRdy53J1kqkRQ040qRpKCjwAAAAAAAAAAAAAUL8sTD0W8zmkeUGgYoJdY6ivobKtGZvvNG6KpIUnePjWcJm0KnxZ-I3ZSGMmGyvOTQQQleiYDhiJr9ZUIAEiAQMP2oJi; n_mh=9LG0OBvzsuBcj8ZxNzj2TIvUSGq0pbEz1jCTMR0yHYU; sid_guard=2e7e3e33f443f4a739fa2116c4ef9d08%7C1786017329%7C5184000%7CMon%2C+05-Oct-2026+11%3A55%3A29+GMT; uid_tt=985aae2dc095dcc934a918f8b0f149a4; uid_tt_ss=985aae2dc095dcc934a918f8b0f149a4; sid_tt=2e7e3e33f443f4a739fa2116c4ef9d08; sessionid=2e7e3e33f443f4a739fa2116c4ef9d08; sessionid_ss=2e7e3e33f443f4a739fa2116c4ef9d08; session_tlb_tag=sttt%7C9%7CLn4-M_RD9Kc5-iEWxO-dCP________-gjLTD0X5e4ePK3Hqqt3a6P1-5xtiC-QgriA34RIujcWA%3D; is_staff_user=false; has_biz_token=false; sid_ucp_v1=1.0.0-KGUwNjlhZTM2NzgzOTA1ZmRhYjk4YjBiZjA0NjhlZmVlMTJmNDgyN2MKIQjkg4CVm630BBCx7NHTBhjvMSAMMMfV7MQGOAdA9AdIBBoCbGYiIDJlN2UzZTMzZjQ0M2Y0YTczOWZhMjExNmM0ZWY5ZDA4; ssid_ucp_v1=1.0.0-KGUwNjlhZTM2NzgzOTA1ZmRhYjk4YjBiZjA0NjhlZmVlMTJmNDgyN2MKIQjkg4CVm630BBCx7NHTBhjvMSAMMMfV7MQGOAdA9AdIBBoCbGYiIDJlN2UzZTMzZjQ0M2Y0YTczOWZhMjExNmM0ZWY5ZDA4; bd_ticket_guard_ts_sign_id=ts.2.21a1b157b9d23b6; _bd_ticket_crypt_cookie=2ae6104f1de50f3638c392c7e4b9d61c; __security_server_data_status=1; login_time=1786017329758; SelfTabRedDotControl=%5B%5D; __security_mc_1_s_sdk_crypt_sdk=bd074dd5-42a0-9bbc; __security_mc_1_s_sdk_cert_key=505aba0e-4aa3-b685; __security_mc_1_s_sdk_sign_data_key_web_protect=79170ef7-4036-bd09; douyin.com; device_web_cpu_core=16; device_web_memory_size=32; architecture=amd64; is_support_rtm_web_ts=1; dy_swidth=1707; dy_sheight=1067; publish_badge_show_info=%220%2C0%2C0%2C1787102216002%22; strategyABtestKey=%221787102220.6%22; ttwid=1%7C8Y2kTOff1xfjH0j8yA2D8dogK5dgx-tPdzr0a6zx9Ro%7C1787102224%7Cacd7c2f10b84abefc90884aed13587516cb53d20df758fac4714e3d187735a82; is_dash_user=1; stream_recommend_feed_params=%22%7B%5C%22cookie_enabled%5C%22%3Atrue%2C%5C%22screen_width%5C%22%3A1707%2C%5C%22screen_height%5C%22%3A1067%2C%5C%22browser_online%5C%22%3Atrue%2C%5C%22cpu_core_num%5C%22%3A16%2C%5C%22device_memory%5C%22%3A32%2C%5C%22downlink%5C%22%3A5.85%2C%5C%22effective_type%5C%22%3A%5C%224g%5C%22%2C%5C%22round_trip_time%5C%22%3A50%7D%22; __ac_nonce=06a851105002f16279eba; __ac_signature=_02B4Z6wo00f01aRbbUwAAIDBKhYbeqXxaMmke2nAAAOU56; download_guide=%223%2F20260819%2F0%22; SEARCH_RESULT_LIST_TYPE=%22single%22; IsDouyinActive=true; csrf_session_id=3bc62c1e6a792c49261fd47a76f9b52d; home_can_add_dy_2_desktop=%221%22; FOLLOW_NUMBER_YELLOW_POINT_INFO=%22MS4wLjABAAAAzE1N8Ob7q6LhhcgtFcMH2ogIKlkk0Nw8MNl0_xJHm_7r7T7aBOR7g06y9q54lADn%2F1787155200000%2F0%2F0%2F1787106915299%22; bd_ticket_guard_client_data=eyJiZC10aWNrZXQtZ3VhcmQtdmVyc2lvbiI6MiwiYmQtdGlja2V0LWd1YXJkLWl0ZXJhdGlvbi12ZXJzaW9uIjoxLCJiZC10aWNrZXQtZ3VhcmQtcmVlLXB1YmxpYy1rZXkiOiJCSUFDVzh6QkwrWGh4YlMvL3Era0U3SE9zN0sxWktsMjJDdUkwQzdkWVFsQWdSRWk1OGs5NnEvZ1JZeUVwVXRDR3FxdEhrMFkrUU5uTXVBNDhGNmZhK2M9IiwiYmQtdGlja2V0LWd1YXJkLXdlYi12ZXJzaW9uIjoyfQ%3D%3D; biz_trace_id=1ecd98c2; bd_ticket_guard_client_data_v2=eyJyZWVfcHVibGljX2tleSI6IkJJQUNXOHpCTCtYaHhiUy8vcStrRTdIT3M3SzFaS2wyMkN1STBDN2RZUWxBZ1JFaTU4azk2cS9nUll5RXBVdENHcXF0SGswWStRTm5NdUE0OEY2ZmErYz0iLCJ0c19zaWduIjoidHMuMi4yMWExYjE1N2I5ZDIzYjZhY2VhZjgxNWYwNTE5YTQ3ZDdmZmFhMDMxMGE0YTJiOGEzYTg2ZDEyZDM1ZmE4MjQxYzRmYmU4N2QyMzE5Y2YwNTMxODYyNGNlZGExNDkxMWNhNDA2ZGVkYmViZWRkYjJlMzBmY2U4ZDRmYTAyNTc1ZCIsInJlcV9jb250ZW50Ijoic2VjX3RzIiwicmVxX3NpZ24iOiJQS2ZNOHpjWU9QZVJBMmw5anZRR0VxOHNxVzFxQlVocHRGSm90K3RSd0NVPSIsInNlY190cyI6IiMrTGJoZHZEejhBQ0swTHBRMFl2WmVzRTdzd0ZLZU5lalBiNXNKQStCQkxoYk1BRGYzN2RHTlFGYWQ4UTcifQ%3D%3D; odin_tt=057adc440efbdc3fe42f5f0711ad578d91459dc78eb87370e30214d827bf1f8081c1dff34416e8d0b7a1293e2edc05194d0c7f0f304982f87de8ea5c944836a3",
        }

    async def search(self, query: str, topk: int = 10):
        logger.info(f"[DouyinEngine] 开始搜索: query='{query}', topk={topk}")
        results = []

        # 对 query 进行 URL 编码，避免特殊字符和中文出错
        encoded_query = urllib.parse.quote(query)

        # 动态更新请求头中的 Referer
        headers = self.headers.copy()
        headers["Referer"] = (
            f"https://www.douyin.com/jingxuan/search/{encoded_query}?"
            "aid=5919da1d-73e9-4c14-9936-38377560f456&type=general"
        )

        # 动态组装 keyword 与 count 参数
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
                headers=headers,
                timeout=10,
            )

            if resp.status_code != 200:
                logger.error(f"[DouyinEngine] 请求失败，状态码: {resp.status_code}")
                return results

            if not resp.text or not resp.text.strip():
                logger.error("[DouyinEngine] 接口返回空数据，签名或 Cookie 已失效。")
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
            logger.error(f"[DouyinEngine] API 解析异常: {e}")
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

    async def search(self, query: str, topk: int) -> List[SearchResult]:
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

    s = GithubEngine()
    result = asyncio.run(s.search("大模型", 3))
    print(result)
