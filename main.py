# """main module.

# FILENAME    : main.py
# Date        : 2026/08/09 20:40:30
# Author      : Huijian Qin
# Version     : 1.0.0
# Description : 网络搜索工具核心调入文件

# Attributes:


# Example:
#     >>> from main import
#     >>>

# """

# import httpx
# from bs4 import BeautifulSoup
# import requests
# import time

# headers = {
#     "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
#     "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
#     "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
#     "Accept-Encoding": "gzip, deflate, br",
#     "Connection": "keep-alive",
#     "Referer": "https://wap.baidu.com/",
# }
# session = requests.Session()

# session.get("https://wap.baidu.com/", headers=headers)
# time.sleep(0.5)
# url = "https://wap.baidu.com/s"
# client = httpx.Client(follow_redirects=True)
# result = client.get(url=url, params={"word": "简历造假"}, headers=headers)
# print(result.status_code)
# print("-" * 50)
# # print(result.text)

# soup = BeautifulSoup(result.text, "lxml")
# print(soup)
# print("-" * 50)
# # with open("baidu_result.html", "w", encoding="utf-8") as f:
# #     f.writelines(str(soup))

# # card = soup.find("article", class_="cosc-card")
# # print(card)
# # r1 = soup.find("article", class_="cosc-card")
# # print(r1)
# import json

# for item in soup.select(".c-result.result"):
#     # print(item)

#     print("-" * 50)
#     article = item.find("article")
#     print(article)
#     ivk_str = article.get("rl-link-data-ivk")
#     ivk_data = json.loads(ivk_str)
#     url = ivk_data.get("control", {}).get("dataUrl")
#     print(url)
#     # if "href" in href:
#     #     print("获取href")
#     #     print(href["href"])
#     print("-" * 50)
# # print(f"href:{href["href"]}")
# # title = item.find("item").get_text(strip=True)
# # print(f"title:{title}")
# 安装：pip install curl_cffi beautifulsoup4 lxml

from curl_cffi import requests
from bs4 import BeautifulSoup
import json
import time


def fetch_baidu_serp(query: str, retry: int = 1) -> str:
    # 1. 创建会话，模拟 Chrome 121（移动端）
    session = requests.Session(impersonate="chrome120")

    # 2. 头信息（与指纹对齐，可选但推荐）
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

    # 3. 先访问首页（获取 Cookie 和必要状态）
    session.get("https://wap.baidu.com/", headers=headers)
    time.sleep(1)  # 模拟人类停顿

    # 4. 发起搜索
    params = {"wd": query}
    resp = session.get(
        "https://wap.baidu.com/s", params=params, headers=headers, timeout=20
    )

    # 5. 校验返回值
    if resp.status_code == 200 and "c-result" in resp.text:
        return resp.text
    elif "百度安全验证" in resp.text:
        if retry > 0:
            time.sleep(2)
            return fetch_baidu_serp(query, retry - 1)
        raise RuntimeError("触发安全验证，请稍后再试或更换IP")
    else:
        raise RuntimeError(f"请求异常，状态码{resp.status_code}，预览{resp.text[:200]}")


# 使用
html = fetch_baidu_serp("简历造假")
soup = BeautifulSoup(html, "lxml")
for item in soup.select(".c-result.result"):
    # print(item)

    # print("-" * 50)
    article = item.find("article")
    # print(article)
    # ivk_str = article.get("rl-link-data-ivk")
    # if ivk_str:
    #     try:
    #         ivk_data = json.loads(ivk_str)
    #         # print(ivk_data)
    #         print("-" * 50)
    #         url = ivk_data.get("control", {}).get("dataUrl")
    #         print(url)
    #         print("-" * 50)
    #     except (json.JSONDecodeError, AttributeError, TypeError):
    #         pass
    # title = item.find("span").get_text(strip=True)
    # print(title)
    snippet = item.find("div", class_="cos-color-text-tiny summary-gap_68jXq")
    print(snippet.text)
    print("-" * 50)
