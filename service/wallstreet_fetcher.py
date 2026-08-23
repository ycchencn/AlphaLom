"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

import requests
from utils.logger import logger
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
import time

# 可选：配置日志
# logging.basicConfig(level=logging.INFO)
# logger = logging.getLogger(__name__)

class WallStreetCNFetcher:
    """
    华尔街见闻（WallStreetCN）文章抓取器
    利用官方 API 直接获取结构化文章内容，无需解析 HTML 页面。
    """

    HOT_API_URL = "https://api-one-wscn.awtmt.com/apiv1/content/articles/hot?period=all"
    ARTICLE_API_TEMPLATE = "https://api-one-wscn.awtmt.com/apiv1/content/articles/{}?extract=0&accept_theme=theme%2Cpremium-theme"

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        "Accept": "application/json",
        "Referer": "https://wallstreetcn.com/"
    }

    @staticmethod
    def _html_to_text(html_str: str) -> str:
        """将 HTML 字符串转为干净的纯文本"""
        if not html_str:
            return ""
        soup = BeautifulSoup(html_str, "html.parser")
        for tag in soup(["script", "style", "aside", "footer", "nav", "div"]):
            if tag.get("style") and "display:none" in tag.get("style"):
                continue
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        return text

    def get_hot_article_ids(self) -> list[int]:
        """
        获取热门文章 ID 列表（合并 day + week，自动去重）
        Returns:
            list[int]: 唯一的文章 ID 列表
        """
        logger.info("Fetching hot article IDs...")
        try:
            resp = requests.get(self.HOT_API_URL, headers=self.HEADERS, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != 20000:
                raise RuntimeError(f"API error: {data.get('message')}")

            seen = set()
            ids = []
            for item in data["data"].get("day_items", []) + data["data"].get("week_items", []):
                aid = item["id"]
                if aid not in seen:
                    ids.append(aid)
                    seen.add(aid)
            logger.info(f"Retrieved {len(ids)} unique article IDs.")
            return ids
        except Exception as e:
            logger.error(f"Failed to fetch hot article IDs: {e}")
            raise

    def fetch_article(self, article_id: int) -> dict:
        """
        抓取单篇文章详情

        Args:
            article_id (int): 文章 ID

        Returns:
            dict: 包含以下字段的字典
                - id: 文章ID
                - title: 标题
                - content_html: 原始HTML内容
                - content_text: 纯文本内容
                - author: 作者名
                - display_time: Unix 时间戳
                - pageviews: 阅读量
                - is_paid: 是否付费文章
                - url: 文章链接
                - error: 若有错误则包含错误信息
        """
        url = self.ARTICLE_API_TEMPLATE.format(article_id)
        result = {
            "id": article_id,
            "title": "",
            "content_html": "",
            "content_text": "",
            "author": "",
            "display_time": 0,
            "pageviews": 0,
            "is_paid": False,
            "url": f"https://wallstreetcn.com/articles/{article_id}",
            "error": None
        }

        try:
            resp = requests.get(url, headers=self.HEADERS, timeout=10)
            if resp.status_code != 200:
                result["error"] = f"HTTP {resp.status_code}"
                return result

            data = resp.json()
            if data.get("code") != 20000:
                result["error"] = data.get("message", "Unknown API error")
                return result

            art = data["data"]
            result.update({
                "title": art.get("title", ""),
                "content_html": art.get("content", ""),
                "content_text": self._html_to_text(art.get("content", "")),
                "author": art.get("author", {}).get("display_name", ""),
                "display_time": art.get("display_time", 0),
                "pageviews": art.get("pageviews", 0),
                "is_paid": art.get("is_need_pay", False)
            })

            # 转换为北京时间字符串
            ts = result["display_time"]
            if ts and isinstance(ts, int) and ts > 0:
                beijing_tz = timezone(timedelta(hours=8))
                dt = datetime.fromtimestamp(ts, tz=beijing_tz)
                result["publish_date"] = dt.strftime("%Y-%m-%d %H:%M:%S")
            else:
                result["publish_date"] = ""

            return result

        except Exception as e:
            result["error"] = str(e)
            return result

    def fetch_articles(self, article_ids: list[int], delay: float = 0.8) -> list[dict]:
        """
        批量抓取多篇文章

        Args:
            article_ids (list[int]): 文章 ID 列表
            delay (float): 每次请求间隔（秒），默认 0.8

        Returns:
            list[dict]: 每篇文章的详情字典列表
        """
        results = []
        total = len(article_ids)
        for i, aid in enumerate(article_ids, 1):
            logger.info(f"[{i}/{total}] Fetching article {aid}...")
            res = self.fetch_article(aid)
            results.append(res)
            if i < total:
                time.sleep(delay)
        return results

if __name__ == '__main__':

    fetcher = WallStreetCNFetcher()

    # 1. 获取热门文章 ID
    ids = fetcher.get_hot_article_ids()[:10]

    # 2. 批量抓取
    articles = fetcher.fetch_articles(ids, delay=1.0)

    # 3. 打印结果
    for art in articles:
        if art["error"]:
            print(f"❌ 失败: ID={art['id']}, 错误: {art['error']}")
        else:
            print(f"\n✅ 标题: {art['title']}")
            print(f"👤 作者: {art['author']}")
            print(f"👁️ 发布时间: {art['publish_date']}")
            print(f"📄 内容预览:\n{art['content_text'][:800]}...\n")
