"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

import re
import pytz
import hashlib
import requests, json
import numpy as np
import pandas as pd
import os
import pickle
import time
from functools import wraps
from datetime import datetime, timedelta, date
from config import feishu_webhook_url
from typing import Any, Callable
from typing import Optional
from bs4 import BeautifulSoup


def validate_stock_code(code: str) -> bool:
    """
    @brief 校验股票代码是否符合 A股、港股或美股的常见格式规范

    @param code: 待校验的股票代码字符串（如 '600519', '00700', 'AAPL'）
    @type code: str

    @return: 若代码格式有效则返回 True，否则返回 False
    @rtype: bool

    @throws: 无（不会抛出异常，输入非字符串将返回 False）

    @example:
        # A股
        assert validate_stock_code("600519") is True
        assert validate_stock_code("000001") is True
        assert validate_stock_code("300750") is True

        # 港股
        assert validate_stock_code("00700") is True
        assert validate_stock_code("700") is True   # 自动补零后为 '00700'
        assert validate_stock_code("9988") is True  # 视为 '09988'

        # 美股
        assert validate_stock_code("AAPL") is True
        assert validate_stock_code("BRK.B") is True
        assert validate_stock_code("TSLA") is True

        # 无效
        assert validate_stock_code("1234567") is False  # 超长
        assert validate_stock_code("abc!") is False     # 含非法字符
        assert validate_stock_code("") is False
    """
    if not isinstance(code, str):
        return False

    code = code.strip().upper()
    if not code:
        return False

    # === 1. 美股：1~5个大写字母，可含一个点（如 BRK.B）
    if re.fullmatch(r'^[A-Z]{1,5}(\.[A-Z]{1,5})?$', code):
        # 确保最多只有一个点（re 已保证），且总长度 <= 6（如 BRK.B 是5字符）
        if code.count('.') <= 1 and len(code) <= 6:
            return True

    # === 2. A股：6位数字，首字符为 0/3/6
    if re.fullmatch(r'^\d{6}$', code):
        if code[0] in {'0', '3', '6'}:
            return True

    # === 3. 港股：原始为1~5位数字，允许用户输入时不补零（如 "700"）
    if code.isdigit() and 1 <= len(code) <= 5:
        # 补零到5位后应在 00001 ~ 99999 范围内（排除全0）
        num = int(code)
        if 1 <= num <= 99999:
            return True

    return False


def normalize_stock_code(code: str, market_hint: Optional[str] = None) -> Optional[str]:
    """
    @brief 将股票代码标准化为统一格式（可选市场提示）

    @param code: 原始股票代码
    @type code: str
    @param market_hint: 可选市场提示，如 'HK', 'US', 'CN'
    @type market_hint: str or None

    @return: 标准化后的代码（如港股补零为5位，美股大写），若无效则返回 None
    @rtype: str or None

    @example:
        assert normalize_stock_code("700") == "00700"
        assert normalize_stock_code("aapl") == "AAPL"
        assert normalize_stock_code("600519") == "600519"
    """
    if not validate_stock_code(code):
        return None

    code = code.strip().upper()

    # 美股：直接返回大写
    if re.fullmatch(r'^[A-Z]{1,5}(\.[A-Z]{1,5})?$', code):
        return code

    # A股：6位数字，直接返回
    if re.fullmatch(r'^\d{6}$', code):
        return code

    # 港股：补零至5位
    if code.isdigit():
        return code.zfill(5)

    return None


def get_date_by_n(n, format='%Y%m%d'):
    """
    返回当前日期前后 n 天的日期字符串。
    :param n: int, 天数。正数表示未来日期，负数表示过去日期。
    :param format: str, 日期格式字符串，默认为 '%Y-%m-%d'。
    :return: str, 日期字符串。
    """
    # 获取当前日期
    current_date = datetime.now()

    # 计算目标日期
    target_date = current_date + timedelta(days=n)

    # 格式化日期字符串
    formatted_date = target_date.strftime(format)

    return formatted_date


def get_date_by_years(date=None, years=1, format='%Y%m%d'):
    """
    计算给定日期加上或减去若干年后的日期，并返回格式化为 %Y%m%d 的字符串。

    :param date: 可选参数，datetime对象。如果未提供，则使用当前日期。
    :param years: 要增加或减少的年数。正数表示未来，负数表示过去。
    :return: 经过年份调整后的日期，格式为 %Y%m%d 的字符串。
    """
    if date is None:
        date = datetime.now()
    else:
        # 确保传入的是datetime对象
        if not isinstance(date, datetime):
            raise ValueError("提供的日期必须是datetime对象")

    try:
        # 尝试直接增加或减少年份
        adjusted_date = date.replace(year=date.year + years)
    except ValueError:
        # 如果遇到闰年的2月29日且目标年不是闰年，调整到2月28日
        if date.month == 2 and date.day == 29:
            if (date.year % 4 == 0 and (date.year % 100 != 0 or date.year % 400 == 0)) and \
                    ((date.year + years) % 4 != 0 or (
                            (date.year + years) % 100 == 0 and (date.year + years) % 400 != 0)):
                adjusted_date = date.replace(month=2, day=28, year=date.year + years)
            else:
                raise
        else:
            raise

    # 格式化日期为 %Y%m%d 格式
    formatted_date = adjusted_date.strftime(format)

    return formatted_date


def df_to_compact_csv(df: pd.DataFrame, max_rows: int = 120) -> str:
    """
    将行情 DataFrame 转为紧凑 CSV 字符串，仅保留关键列和最近 max_rows 行。

    假设 df 的索引是 date (DatetimeIndex)，并包含 open/high/low/close/volume 列（不区分大小写）。
    """
    # 确保是 DatetimeIndex
    if not isinstance(df.index, pd.DatetimeIndex):
        if 'date' in df.columns:
            df = df.set_index('date')
        else:
            raise ValueError("DataFrame must have DatetimeIndex or 'date' column.")

    df = df.sort_index()

    # 列名映射（兼容大小写）
    col_map = {}
    for col in df.columns:
        lower = col.lower()
        if 'open' in lower:
            col_map['open'] = col
        elif 'high' in lower:
            col_map['high'] = col
        elif 'low' in lower:
            col_map['low'] = col
        elif 'close' in lower:
            col_map['close'] = col
        elif 'volume' in lower or 'vol' in lower:
            col_map['volume'] = col

    if not all(k in col_map for k in ['open', 'high', 'low', 'close', 'volume']):
        missing = [k for k in ['open', 'high', 'low', 'close', 'volume'] if k not in col_map]
        raise ValueError(f"Missing required columns: {missing}")

    # 选取最近 max_rows 行
    recent_df = df.tail(max_rows).copy()

    # 提取并重命名
    compact_df = recent_df[
        [col_map['open'], col_map['high'], col_map['low'], col_map['close'], col_map['volume']]].copy()
    compact_df.columns = ['开盘', '最高', '最低', '收盘', '成交量']

    # 转为 CSV 字符串（无 header，无 index name）
    csv_str = compact_df.to_csv(
        index=True,
        header=False,
        date_format='%Y-%m-%d',
        float_format='%.2f',
        lineterminator='\n'
    ).strip()

    return csv_str


def convert_date_format(date_str, input_format="%Y%m%d", output_format="%Y-%m-%d"):
    """
    将日期字符串从一种格式转换为另一种格式。

    :param date_str: 输入的日期字符串，如 "20250101"
    :param input_format: 输入字符串的格式，默认为 "%Y%m%d"（对应 20250101）
    :param output_format: 输出字符串的格式，默认为 "%Y-%m-%d"（对应 2025-01-01）
    :return: 转换后的日期字符串
    :raises ValueError: 如果输入日期格式不匹配
    """
    dt = datetime.strptime(date_str, input_format)
    return dt.strftime(output_format)


def _dict_to_markdown_recursive(data, indent=0):
    markdown = ""
    prefix = "  " * indent
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                markdown += f"{prefix}- **{key}**:\n"
                markdown += _dict_to_markdown_recursive(value, indent + 1)
            else:
                markdown += f"{prefix}- **{key}**: {value}\n"
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, (dict, list)):
                markdown += f"{prefix}- \n"
                markdown += _dict_to_markdown_recursive(item, indent + 1)
            else:
                markdown += f"{prefix}- {item}\n"
    else:
        markdown += f"{prefix}{data}\n"
    return markdown


def dict_to_markdown_recursive(data: dict) -> str:
    return _dict_to_markdown_recursive(data)


def calculate_opportunity_score(df):
    """
    计算ETF的机会值，基于过去一周和一个月的涨跌幅
    :param df: 日期因子，包含['date', 'code', 'price']，已按日期排序
    :return: 包含 opportunity_score 的 DataFrame
    """
    df['w_return'] = df['price'].pct_change(periods=5) * 100  # 最近一周（5日）回报
    df['m_return'] = df['price'].pct_change(periods=20) * 100  # 最近一个月（20日）回报
    df['trend_acceleration'] = df['w_return'] - df['w_return'].shift(5)  # 前一周的周回报（滞后）
    # 每列归一化，假设我们知道历史最大最小
    w_max, w_min = df['w_return'].max(), df['w_return'].min()
    m_max, m_min = df['m_return'].max(), df['m_return'].min()
    t_max, t_min = df['trend_acceleration'].max(), df['trend_acceleration'].min()
    w_score = (df['w_return'] - w_min) / (w_max - w_min) * 100
    m_score = (df['m_return'] - m_min) / (m_max - m_min) * 100
    t_score = (df['trend_acceleration'] - t_min) / (t_max - t_min) * 100
    df['opportunity_score'] = (0.4 * w_score) + (0.4 * m_score) + (0.2 * t_score)
    return df


def date_to_timestamp(date_str, _format='%Y-%m-%d'):
    # 将字符串转换为 datetime 对象
    date_obj = datetime.strptime(date_str, _format)
    # 将 datetime 对象转换为时间戳
    timestamp = int(date_obj.timestamp())
    return timestamp


def get_hourly_timestamps():
    # 获取当前时间
    now = datetime.datetime.now()

    # 计算当前小时的开始时间
    current_hour_start = now.replace(minute=0, second=0, microsecond=0)

    # 计算上一个小时的开始时间
    last_hour_start = current_hour_start - datetime.timedelta(hours=1)

    # 获取时间戳（毫秒）
    current_hour_start_timestamp = int(current_hour_start.timestamp() * 1000)
    last_hour_start_timestamp = int(last_hour_start.timestamp() * 1000)

    return current_hour_start_timestamp, last_hour_start_timestamp


def is_weekend(_date=None):
    """
    @brief 判断给定的日期是否是周末

    @param date: 要判断的日期，默认为今天
    @type date: datetime.date 或 datetime.datetime

    @return: 如果是周末返回 True，否则返回 False
    @rtype: bool

    @throws ValueError: 如果输入的日期格式不正确

    @example:
        # 示例用法
        print(is_weekend())  # 输出: 根据今天是否是周末返回 True 或 False
        date1 = datetime(2023, 10, 7)  # 星期六
        date2 = datetime(2023, 10, 8)  # 星期日
        date3 = datetime(2023, 10, 9)  # 星期一

        print(is_weekend(date1))  # 输出: True
        print(is_weekend(date2))  # 输出: True
        print(is_weekend(date3))  # 输出: False
    """
    if _date is None:
        _date = date.today()

    if not isinstance(_date, (date, datetime)):
        raise ValueError("输入的日期必须是 datetime.date 或 datetime.datetime 类型")

    # weekday() 返回 0 表示周一，6 表示周日
    return _date.weekday() >= 5


def get_date_by_n(n, _format='%Y%m%d'):
    """
    返回当前日期前后 n 天的日期字符串。
    :param n: int, 天数。正数表示未来日期，负数表示过去日期。
    :param _format: str, 日期格式字符串，默认为 '%Y-%m-%d'。
    :return: str, 日期字符串。
    """
    # 获取当前日期
    current_date = datetime.now()
    # 计算目标日期
    target_date = current_date + timedelta(days=n)
    # 格式化日期字符串
    formatted_date = target_date.strftime(_format)
    return formatted_date


def get_offset_date(date_str: str, n: int) -> str:
    """
    计算给定日期的前 n 天或后 n 天。

    参数:
        date_str (str): 输入日期字符串，格式为 'YYYYMMDD' (例如: '20260309')
        n (int): 天数偏移量。
                 - 正数 (n > 0): 返回后 n 天 (未来)
                 - 负数 (n < 0): 返回前 n 天 (过去)
                 - 零 (n = 0): 返回原日期

    返回:
        str: 计算后的日期字符串，格式为 'YYYYMMDD'
    """
    try:
        # 1. 将字符串解析为 datetime 对象
        # 格式代码: %Y(4位年) %m(2位月) %d(2位日)
        current_date = datetime.strptime(date_str, "%Y%m%d")

        # 2. 计算偏移后的日期
        target_date = current_date + timedelta(days=n)

        # 3. 将结果格式化回字符串
        return target_date.strftime("%Y%m%d")

    except ValueError as e:
        return f"错误: 日期格式不正确或日期无效 ({e})"


def get_today(_format="%Y%m%d"):
    """
    获取今天
    """
    # return "20250221"
    return datetime.now(pytz.timezone('Asia/Shanghai')).strftime(_format)


def get_now(_format="%Y-%m-%d %H:%M:%S"):
    """
    获取今天
    """
    return datetime.now(pytz.timezone('Asia/Shanghai')).strftime(_format)


def get_timestamp():
    """
    获取时间戳
    """
    return datetime.timestamp(datetime.now(pytz.timezone('Asia/Shanghai')))


def get_timestamp_mill():
    """
    获取时间戳
    """
    return int(datetime.timestamp(datetime.now(pytz.timezone('Asia/Shanghai'))) * 1000)


def get_timestamp_hour():
    """
    获取时间戳，小时级
    """
    # 获取当前时间
    now = datetime.now()
    # 设置为当前小时的开始时间（即分钟、秒和微秒都设为0）
    hour_start = now.replace(minute=0, second=0, microsecond=0)
    # 将datetime对象转换为时间戳
    return int(hour_start.timestamp())


def get_date_by_months(_date=None, months=1):
    """
    计算给定日期加上或减去若干月后的日期，并返回格式化为 %Y%m%d 的字符串。

    :param _date: 可选参数，datetime对象。如果未提供，则使用当前日期。
    :param months: 要增加或减少的月数。正数表示未来，负数表示过去。
    :return: 经过月份调整后的日期，格式为 %Y%m%d 的字符串。
    """
    if _date is None:
        _date = datetime.now()
    else:
        # 确保传入的是datetime对象
        if not isinstance(_date, datetime):
            raise ValueError("提供的日期必须是datetime对象")

    # 计算目标年份和月份
    year = _date.year + (_date.month - 1 + months) // 12
    month = (_date.month - 1 + months) % 12 + 1

    # 尝试创建新的日期
    try:
        adjusted_date = _date.replace(year=year, month=month)
    except ValueError:
        # 如果目标月份的天数少于当前日期的天数（例如3月31日加一个月变成4月30日）
        if month == 2 and _date.day > 28:
            # 处理闰年的2月29日
            if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) and _date.day == 29:
                adjusted_date = _date.replace(year=year, month=month, day=29)
            else:
                adjusted_date = _date.replace(year=year, month=month, day=28)
        else:
            # 找到目标月份的最后一天
            last_day_of_month = (datetime(year, month + 1, 1) - timedelta(days=1)).day
            adjusted_date = _date.replace(year=year, month=month, day=min(_date.day, last_day_of_month))

    # 格式化日期为 %Y%m%d 格式
    formatted_date = adjusted_date.strftime('%Y%m%d')

    return formatted_date


def half_round_to_hundred(value):
    """
    计算给定值的一半，并将结果四舍五入到最接近的100的倍数。

    参数:
    value -- 需要处理的原始数值

    返回:
    处理后的结果，是100的倍数
    """
    # 计算一半
    half_value = value / 2

    # 四舍五入到最接近的100的倍数
    rounded_half_value = round(half_value / 100) * 100

    return rounded_half_value


def send_feishu_markdown_message(title, webhook_url=feishu_webhook_url, markdown_text='', header_color="blue",
                                 dry_run=False):
    """
    通过飞书 Webhook 发送 Markdown 格式的消息。

    :param title: 飞书机器人的 标题
    :param webhook_url: 飞书机器人的 Webhook URL
    :param markdown_text: 要发送的 Markdown 格式的文本
    :param header_color: 表头颜色
    :param dry_run: 测试标记
    :return: 发送请求的响应
    """
    # 构建消息体
    payload = {
        "msg_type": "interactive",
        "card": {
            "schema": "2.0",
            "config": {
                "update_multi": True,
                "style": {
                    "text_size": {
                        "normal_v2": {
                            "default": "normal",
                            "pc": "normal",
                            "mobile": "heading"
                        }
                    }
                }
            },
            "body": {
                "direction": "vertical",
                "padding": "12px 12px 12px 12px",
                "elements": [
                    {
                        "tag": "markdown",
                        "content": markdown_text,
                        "text_align": "left",
                        "text_size": "normal_v2",
                        "margin": "0px 0px 0px 0px"
                    }
                ]
            },
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": title
                },
                "template": header_color,
                "padding": "12px 12px 12px 12px"
            }
        }
    }

    if dry_run:
        print(payload)
        return

    # 发送 POST 请求
    response = requests.post(
        webhook_url,
        headers={
            'Content-Type': 'application/json'
        },
        data=json.dumps(payload)
    )

    # 检查响应状态码
    if response.status_code == 200:
        return response
    else:
        return False


def is_etf(stock_code):
    """
    判断给定的股票代码是否为ETF
    :param stock_code: 股票代码（字符串格式，例如"510050"）
    :return: True（是ETF）或 False（不是ETF）
    """
    # 检查股票代码是否为6位数字
    if not isinstance(stock_code, str) or len(stock_code) != 6 or not stock_code.isdigit():
        return False

    # 获取代码的前3位
    prefix = stock_code[:3]

    # 定义ETF的代码前缀范围
    etf_prefixes = ["510", "511", "512", "513", "515", "560", "518", "159", "16", "520", "508", "180", "516"]

    # 检查代码前缀是否在ETF范围内
    if prefix in etf_prefixes:
        return True
    elif prefix.startswith("588"):  # 科创板ETF的特殊前缀
        return True
    else:
        return False


# 归一化评分
def normalize_score(value, min_value, max_value):
    return (value - min_value) / (max_value - min_value) * 100


def calculate_market_temperature(data, weighted_turnover_ratios, market_limit_data):
    """
    计算市场温度

    :param data: 包含市场数据的列表，每个元素是一个字典，包含以下键：
        - 'weight_percentage': 权重百分比
        - 'daily_change': 日变化率
        - 'year_to_date': 年初至今的变化率
    :param weighted_turnover_ratios: 加权换手率
    :param market_limit_data: 市场涨跌幅数据
    :return: 计算出的市场温度
    :rtype: float
    """

    # 基础温度
    temperature_base = 30

    # 计算总权重
    total_weight = sum(item['weight_percentage'] for item in data)

    # 计算加权日变化和年初至今变化的总和
    total_daily_change = sum(item['weight_percentage'] * item['daily_change'] for item in data)

    # 使用月涨跌幅参与计算
    total_month_to_date = sum(item['weight_percentage'] * item['month_to_date'] for item in data)

    # 计算市场整体变化情况
    market_change = (total_daily_change + total_month_to_date) / total_weight

    # 涨跌幅比率
    rw_ratio = (market_limit_data['rising'] - market_limit_data['falling']) / (
            market_limit_data['rising'] + market_limit_data['falling'])

    # 根据市场变化调整基础温度
    temperature_base += (market_change * 0.75)

    # 根据加权换手率进一步调整温度
    temperature_base += (weighted_turnover_ratios * 0.15)

    # 根据涨跌幅比率进一步调整温度
    temperature_base += (rw_ratio * 0.5)

    # 将市场温度限制在0-60之间
    market_temperature = np.clip(temperature_base, 0, 60)

    return market_temperature


def get_market_temp_zone(market_temp):
    """
    @brief 根据市场温度值返回对应的市场温度区间描述

    @param market_temp: 市场温度数值，用于判断市场所处的温度区间
    @type market_temp: float or int

    @return: 返回市场温度区间字符串，可能的取值为 'glacial'、'cold'、'neutral'、'warmed'、'hot'
    @rtype: str or None

    @throws: 无

    @example:
        # 示例用法
        zone = self.get_market_temp_zone(32)
        print(zone)  # 输出: cold
    """
    if market_temp == -1:
        return None
    # 市场温度区间划分
    if 1 < market_temp <= 30:
        temp_zone = 'glacial'  # 极端冰点
    elif 30 < market_temp <= 35:
        temp_zone = 'cold'  # 冷清
    elif 36 < market_temp < 38:
        temp_zone = 'neutral'  # 中性
    elif 38 <= market_temp <= 40:
        temp_zone = 'warmed'  # 微热
    else:
        temp_zone = 'hot'  # 过热
    return temp_zone


def timestamp_to_date(timestamp, fmt='%Y-%m-%d %H:%M:%S'):
    """
    将时间戳转换为指定格式的日期字符串。

    参数:
        timestamp (int or float): Unix 时间戳（秒或毫秒）
        fmt (str): 日期格式，默认为 '%Y-%m-%d %H:%M:%S'

    返回:
        str: 格式化后的日期字符串
    """
    # 判断是否是毫秒时间戳（长度大于10位）
    if timestamp > 1e10:
        timestamp = timestamp / 1000  # 转换为秒

    dt = datetime.fromtimestamp(timestamp)
    return dt.strftime(fmt)


def string_to_md5(text: str) -> str:
    """
    将输入字符串转换为 MD5 哈希值（32位小写十六进制字符串）。

    :param text: 要哈希的原始字符串
    :return: MD5 哈希值（如 'd41d8cd98f00b204e9800998ecf8427e'）
    :rtype: str
    """
    if not isinstance(text, str):
        raise TypeError("Input must be a string")

    # 将字符串编码为 UTF-8 字节，然后计算 MD5
    md5_hash = hashlib.md5(text.encode('utf-8')).hexdigest()
    return md5_hash


def df_cache(cache_dir='df_cache', default_ttl=43200):  # 12小时 = 43200秒
    def decorator(func: Callable) -> Callable:
        os.makedirs(cache_dir, exist_ok=True)

        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            try:
                # 构造缓存键
                key_repr = (args, tuple(sorted(kwargs.items())))
                key_bytes = pickle.dumps(key_repr, protocol=4)
                cache_key = hashlib.sha256(key_bytes).hexdigest()
                cache_path = os.path.join(cache_dir, f"{func.__name__}_{cache_key}.pkl")
            except Exception as e:
                raise ValueError(f"无法序列化函数参数用于缓存: {e}")

            # 检查缓存是否存在且未过期
            if os.path.exists(cache_path):
                try:
                    with open(cache_path, 'rb') as f:
                        data = pickle.load(f)
                        result, timestamp = data['result'], data['timestamp']

                    # 检查是否过期
                    if time.time() - timestamp < default_ttl:
                        return result
                    # 如果过期，继续执行函数（自动更新缓存）
                except Exception:
                    # 如果反序列化失败或格式错误，也重新计算
                    pass

            # 执行函数
            result = func(*args, **kwargs)

            # 保存结果 + 当前时间戳
            try:
                with open(cache_path, 'wb') as f:
                    pickle.dump({
                        'result': result,
                        'timestamp': time.time()
                    }, f)
            except Exception as e:
                print(f"缓存写入失败: {e}")
                # 即使缓存失败，也要返回结果
            return result

        return wrapper

    return decorator


def fix_stock_symbol(symbol):
    """
    根据股票代码前缀自动添加市场后缀。
    【已修复】增加长度校验，防止 5 位港股 (如 00005) 被误判为 A 股。

    规则详情:
    - A 股 (必须是 6 位数字):
        - 深交所 (000, 001, 002, 300, 301, 159) -> .SHE
        - 上交所 (600-605, 688, 689, 510-519, 588) -> .SHG
    - 港股 (纯数字，非 6 位 A 股格式):
        - 去掉第一位 '0' + .HK
    - 美股 (包含字母) -> .US
    """

    # 1. 标准化输入
    if not isinstance(symbol, str):
        code = str(symbol).strip()
    else:
        code = symbol.strip()

    # 2. 【新增】检查是否已包含后缀
    # 定义常见后缀列表 (不区分大小写检查，但返回时保持原样或统一格式)
    # 这里我们检查代码中是否包含这些后缀标记
    known_suffixes = ['.SHG', '.SHE', '.HK', '.US', '.shg', '.she', '.hk', '.us']

    # 只要包含任意一个已知后缀，就直接返回原代码
    # 使用 lower() 进行不区分大小写的匹配
    for suffix in known_suffixes:
        if code.endswith(suffix):
            return code.upper()

    # 如果中间包含点号但不是标准后缀，也可以选择直接返回或按需处理
    # 这里为了稳健，如果有点号且后面有内容，通常视为已格式化
    if '.' in code:
        # 可选策略：如果有点号但没匹配到上述标准后缀，是原样返回还是报错？
        # 这里选择原样返回，避免破坏用户自定义格式
        return code

    if not code:
        return code

    # 2. 判断纯数字代码
    if code.isdigit():
        len_code = len(code)

        # --- A 股判断 (严格限制长度为 6 位) ---
        if len_code == 6:
            prefix = code[:3]

            # 深交所前缀列表
            shenzhen_prefixes = ['000', '001', '002', '300', '301', '159', '003']
            if prefix in shenzhen_prefixes:
                return f"{code}.SHE"

            # 上交所前缀列表
            shanghai_prefixes = ['600', '601', '602', '603', '605', '688', '689', '588', '561']
            # 510-519 范围判断
            if prefix in shanghai_prefixes or (prefix.startswith('51') and prefix[2].isdigit()):
                return f"{code}.SHG"

            prefix_bj = code[:2]
            # 北交所前缀列表
            beijing_prefixes = ['83', '84', '85', '86', '87', '88', '89', '92']
            # 范围判断
            if prefix_bj in beijing_prefixes:
                return f"{code}.BJ"

            raise Exception(f'没有匹配到股票代码后缀，{code}')

        # --- 港股判断 ---
        # 逻辑：如果是纯数字，且【没有被判定为 A 股】
        # 通常港股长度为 4 或 5 位 (如 00005, 00700)，但也可能有其他长度
        # 只要不是 6 位的标准 A 股格式，且看起来像港股代码，就按港股处理
        if 4 <= len_code <= 6:
            # 去掉第一位的 '0'
            if code.startswith('0'):
                clean_code = code[1:]
            else:
                clean_code = code
            return f"{clean_code}.HK"

        # 其他纯数字情况 (如长度过短)，原样返回
        return code

    # 3. 判断美股 (包含字母)
    if not code.isdigit():
        if code.lower().endswith('.us'):
            return code
        return f"{code}.US"

    # 4. 兜底
    return code


def extract_html(llm_response: str, prefer_code_block: bool = True) -> str:
    """
    从大模型回复中提取 HTML 内容

    Args:
        llm_response: 大模型的原始回复文本
        prefer_code_block: 是否优先提取 ```html 代码块
    """
    if prefer_code_block:
        # 优先匹配 ```html 代码块
        pattern = r"```\s*(?:html)?\s*\n?(.*?)```"
        match = re.search(pattern, llm_response, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()

    # 尝试匹配完整 HTML 文档
    full_html = re.search(
        r"(<!DOCTYPE[^>]*>\s*)?<html[^>]*>.*?</html>",
        llm_response, re.DOTALL | re.IGNORECASE
    )
    if full_html:
        return full_html.group(0)

    # 尝试匹配 <body>...</body>
    body = re.search(r"<body[^>]*>.*?</body>", llm_response, re.DOTALL | re.IGNORECASE)
    if body:
        return body.group(0)

    # 最后用 BeautifulSoup 兜底，提取看起来像 HTML 的部分
    soup = BeautifulSoup(llm_response, "html.parser")
    # 找第一个 HTML 标签作为起点
    for tag in soup.find_all(True):
        if tag.name in ('html', 'body', 'div', 'main', 'section'):
            return str(tag)

    # 如果什么都没找到，返回去空白后的原文
    return llm_response.strip()


# --- 测试示例 ---
if __name__ == "__main__":
    base_date = "20260309"

    # 场景 1: 获取后 5 天 (2026-03-14)
    future_date = get_offset_date(base_date, 5)
    print(f"{base_date} 后 5 天: {future_date}")

    # 场景 2: 获取前 10 天 (2026-02-27)
    past_date = get_offset_date(base_date, -10)
    print(f"{base_date} 前 10 天: {past_date}")

    # 场景 3: 跨月/跨年测试 (假设从 2026-01-02 向前推 5 天)
    cross_year = get_offset_date("20260102", -5)
    print(f"20260102 前 5 天: {cross_year}")
