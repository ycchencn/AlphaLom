"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

import requests

headers_baidu = {
    'Host': 'news.10jqka.com.cn',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:136.0) Gecko/20100101 Firefox/136.0',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2',
    'Accept-Encoding': 'gzip, deflate, br, zstd',
    'Connection': 'keep-alive'
}

def get_realtime_news_from_ths(page=1, pagesize=100):
    """
    https://news.10jqka.com.cn/tapp/news/push/stock/?page=1&tag=&track=website&pagesize=100
    """
    response = requests.get(f"https://news.10jqka.com.cn/tapp/news/push/stock/?page={page}&tag=&track=website&pagesize={pagesize}", headers=headers_baidu, timeout=5)
    return response.json()

def get_realtime_news_from_ths_short(page=1, pagesize=100):
    """

    """
    short = []
    res = get_realtime_news_from_ths(page=page, pagesize=pagesize)
    for new in res['data']['list']:
        short.append(new)
        # short.append(f"digest:{new['digest']}, tag: {new['tag']}, ctime:{new['ctime']}")
    return short

if __name__ == '__main__':

    news_short = get_realtime_news_from_ths_short(page=1, pagesize=20)

    for i in news_short:
        print(i)
        print()
