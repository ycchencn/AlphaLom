"""
 * @author Yc
 * 实时财经快讯抓取（原 alphalom.news，alphalom 包已废弃后迁入 utils）。

 * 数据源：同花顺财经快讯接口（news.10jqka.com.cn）。
 * ⚠️ 这是外部抓取源，返回结构可能随上游调整而漂移；调用方（job_news_feed_analysis）
 * 已按「拿不到就降级」的方式消费，抓取层保持薄封装、不做过度解析。
"""

import requests

headers_ths = {
    'Host': 'news.10jqka.com.cn',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:136.0) Gecko/20100101 Firefox/136.0',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2',
    'Accept-Encoding': 'gzip, deflate, br, zstd',
    'Connection': 'keep-alive'
}


def get_realtime_news_from_ths(page=1, pagesize=100):
    """
    拉同花顺实时快讯原始 JSON。
    https://news.10jqka.com.cn/tapp/news/push/stock/?page=1&tag=&track=website&pagesize=100
    """
    response = requests.get(
        f"https://news.10jqka.com.cn/tapp/news/push/stock/?page={page}&tag=&track=website&pagesize={pagesize}",
        headers=headers_ths, timeout=5)
    return response.json()


def get_realtime_news_from_ths_short(page=1, pagesize=100):
    """拉同花顺实时快讯，返回 data.list 里的快讯数组（每条含 digest/tag/ctime 等）。"""
    short = []
    res = get_realtime_news_from_ths(page=page, pagesize=pagesize)
    for new in res['data']['list']:
        short.append(new)
    return short


if __name__ == '__main__':
    news_short = get_realtime_news_from_ths_short(page=1, pagesize=20)
    for i in news_short:
        print(i)
        print()
