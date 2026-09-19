"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

import requests
import time
from typing import Dict, List, Any, Optional


class XueqiuAPI:
    """
    雪球API封装类（简化版）
    不使用复杂的对象映射，直接返回字典/列表
    """
    BASE_URL = "https://stock.xueqiu.com/v5/stock/screener"

    xq_a_token = "ca35d6d2fa5e735759056fc62797546c18062187"

    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self.session = requests.Session()
        # 修改这里的 headers，添加 Cookie
        self.session.headers.update({
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Host": "xueqiu.com",
            "Pragma": "no-cache",
            "Referer": "https://xueqiu.com/hq",
            "sec-ch-ua": '" Not A;Brand";v="99", "Chromium";v="100", "Google Chrome";v="100"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Safari/537.36",
            "X-Requested-With": "XMLHttpRequest",
            'Cookie': f"xq_a_token={self.xq_a_token};"
        })

    def get_kline_data(self,
                       symbol: str,
                       period: str = 'day',
                       count: int = -284,
                       begin_timestamp: Optional[int] = None,
                       indicators: str = 'kline,pe,pb,ps,pcf,market_capital') -> List[Dict[str, Any]]:
        """
        获取股票 K 线历史数据

        :param symbol: 股票代码 (如: SH688583)
        :param period: 周期 ('day' 日线, 'week' 周线, 'month' 月线, '5m' 5分钟等)
        :param count: 获取数量 (负数: 获取指定数量的历史数据; 正数: 获取指定数量的未来数据)
        :param begin_timestamp: 开始时间戳 (秒级)。如果为 None，则从当前时间开始。
        :param indicators: 需要获取的指标，多个用逗号分隔
        :return: 包含 K 线数据的列表
        """
        url = "https://stock.xueqiu.com/v5/stock/chart/kline.json"

        # 处理时间戳 (接口需要毫秒级)
        if begin_timestamp is None:
            # 如果没传时间，默认使用当前时间 (毫秒)
            begin_ms = int(time.time() * 1000)
        else:
            # 转换为毫秒
            begin_ms = begin_timestamp

        params = {
            'symbol': symbol,
            'begin': begin_ms,
            'period': period,
            'type': 'before',  # 固定为 'before' 配合负数 count 使用
            'count': count,
            'indicator': indicators
        }

        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
            # response = self.session.get('https://stock.xueqiu.com/v5/stock/chart/kline.json?symbol=SH688583&begin=1769953211741&period=day&type=before&count=-284&indicator=kline,pe,pb,ps,pcf,market_capital,agt,ggt,balance')
            if response.status_code != 200:
                print(f"K线请求失败: HTTP {response.status_code}")
                return []

            json_data = response.json()

            if json_data.get('error_code') != 0:
                print(f"API 错误: {json_data.get('error_description')}")
                return []

            # --- 数据解析 ---
            # 参考文档中的 Column 映射
            columns = json_data['data']['column']
            items = json_data['data']['item']

            result_list = []
            for item in items:
                # 将数组映射为字典
                row_dict = {}
                for idx, value in enumerate(item):
                    col_name = columns[idx]
                    # 特殊处理时间戳，转换为可读格式 (可选)
                    if col_name == 'timestamp':
                        # 保留原始时间戳，也可以转换为 datetime 对象
                        row_dict['timestamp_s'] = value // 1000  # 转回秒
                        # row_dict['date'] = time.strftime('%Y-%m-%d', time.localtime(value//1000))
                    row_dict[col_name] = value
                result_list.append(row_dict)

            print(f"成功获取 {symbol} 的 {period} 线数据，共 {len(result_list)} 条记录。")
            return result_list

        except Exception as e:
            print(f"获取 K 线数据异常: {str(e)}")
            return []

    def get_all_quotes(self,
                       size: int = 90,
                       order: str = 'desc',
                       order_by: str = 'percent',
                       market: str = 'CN',
                       stock_type: str = 'sh_sz') -> List[Dict]:
        """
        循环获取所有股票行情数据

        :param size: 每页数量 (建议90，最大值)
        :return: 包含所有股票数据的列表
        """
        all_items = []
        page = 1

        # 第一步：获取第一页，主要是为了拿到总数量(count)
        print(f"正在获取第 {page} 页...")
        result = self._fetch_page(page, size, order, order_by, market, stock_type)

        if result["error_code"] != 0:
            print(f"请求失败: {result['error_description']}")
            return []

        # 提取数据
        total_count = result["data"]["count"]
        all_items.extend(result["data"]["list"])

        # 计算总页数
        total_pages = (total_count // size) + (1 if total_count % size > 0 else 0)
        print(f"共找到 {total_count} 条数据，预计共 {total_pages} 页...")

        # 第二步：循环获取剩余页面
        # 从第2页开始
        for page_num in range(2, total_pages + 1):
            print(f"正在获取第 {page_num} 页... ({len(all_items)}/{total_count})")

            # 添加延时，防止请求过快被封IP (建议0.5-1秒)
            time.sleep(0.5)

            page_result = self._fetch_page(page_num, size, order, order_by, market, stock_type)

            if page_result["error_code"] == 0:
                all_items.extend(page_result["data"]["list"])
            else:
                print(f"第 {page_num} 页获取失败，错误码: {page_result['error_code']}")
                # 可以选择 continue 尝试下一页，或者 break 停止
                continue

        print(f"获取完成！总计 {len(all_items)} 条数据。")
        return all_items

    def _fetch_page(self, page: int, size: int, order: str, order_by: str, market: str, stock_type: str) -> Dict[
        str, Any]:
        """
        私有方法：获取单页数据
        """
        url = "https://stock.xueqiu.com/v5/stock/screener/quote/list.json"
        params = {
            'page': page,
            'size': size,
            'order': order,
            'order_by': order_by,
            'market': market,
            'type': stock_type
        }

        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
            # 如果返回400，通常是因为Cookie失效
            if response.status_code != 200:
                return {
                    "error_code": response.status_code,
                    "error_description": f"HTTP Error: {response.status_code}",
                    "data": None
                }

            json_data = response.json()
            return {
                "error_code": json_data.get("error_code", -1),
                "error_description": json_data.get("error_description", ""),
                "data": json_data.get("data")
            }

        except Exception as e:
            return {
                "error_code": -999,
                "error_description": f"Exception: {str(e)}",
                "data": None
            }

    def get_quote_list(self,
                       page: int = 1,
                       size: int = 90,
                       order: str = 'desc',
                       order_by: str = 'percent',
                       market: str = 'CN',
                       stock_type: str = 'sh_sz') -> Dict[str, Any]:
        """
        获取股票行情列表

        :return: 返回包含 error 和 data 的字典
                 data['list'] 是原始的字典列表
        """
        url = f"{self.BASE_URL}/quote/list.json"
        params = {
            'page': page,
            'size': size,
            'order': order,
            'order_by': order_by,
            'market': market,
            'type': stock_type
        }

        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            json_data = response.json()

            # 直接返回处理后的数据结构
            # 你可以在这里做简单的数据清洗或字段过滤
            # 如果不需要清洗，甚至可以直接 return json_data

            result = {
                "error_code": json_data.get("error_code", -1),
                "error_description": json_data.get("error_description", ""),
                "data": None
            }

            if result["error_code"] == 0 and "data" in json_data:
                raw_data = json_data["data"]
                # 保留大部分原始数据，只做必要的类型检查或简化
                processed_data = {
                    "count": raw_data.get("count", 0),
                    "list": raw_data.get("list", [])  # list 里的每一项还是 dict
                }
                result["data"] = processed_data

            return result

        except Exception as e:
            return {
                "error_code": -999,
                "error_description": f"Request failed: {str(e)}",
                "data": None
            }


_api = XueqiuAPI()


def get_market_data_from_xueqiu(page=1, size=30):
    # 调用方法
    return _api.get_quote_list(page=page, size=size)


def get_all_market_data_from_xueqiu():
    # 调用方法
    return _api.get_all_quotes()


# --- 使用示例 ---
if __name__ == "__main__":

    # 示例1: 获取百济神州 (SH688583) 的最近 284 天日线数据 (包含 PE/PB)
    # 注意: 这里的 Cookie 必须有效，否则会报 400
    data = _api.get_kline_data(
        symbol="SH688583",
        begin_timestamp=1769953211741,
        period="day",
        count=-284,  # 获取过去284天的数据
        indicators="kline,pe,pb,ps,pcf,market_capital,agt,ggt,balance"  # 指定指标
    )

    # 打印第一条数据看看
    if data:
        first_day = data
        print(f"日期: {first_day['timestamp_s']}, "
              f"开盘: {first_day['open']}, "
              f"收盘: {first_day['close']}, "
              f"PE-TTM: {first_day.get('pe', 'N/A')}")
