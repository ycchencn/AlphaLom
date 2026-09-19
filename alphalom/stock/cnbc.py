"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

import re
from typing import Optional, Dict, Any
from urllib.parse import urlparse


def parse_financial_value(value_str: str) -> float:
    """辅助函数：将带有 K, M, B, T 的字符串转换为浮点数"""
    if not value_str or value_str == "":
        return 0.0

    multipliers = {'K': 1e3, 'M': 1e6, 'B': 1e9, 'T': 1e12}
    match = re.match(r"([+-]?[\d,.]+)([KMBT])?", value_str.strip())
    if match:
        num_part = float(match.group(1).replace(',', ''))
        suffix = match.group(2)
        if suffix:
            return num_part * multipliers[suffix]
        else:
            return num_part
    return float(value_str.replace(',', ''))  # Fallback for pure numbers


def parse_percentage(percentage_str: str, _round=5) -> Optional[float]:
    """辅助函数：将百分比字符串（如 '2.21%'）转换为小数（如 0.0221）"""
    if not percentage_str or percentage_str == "":
        return 0
    # 移除百分号并转换为浮点数，然后除以 100
    clean_str = percentage_str.replace('%', '').strip()
    try:
        return round(float(clean_str) / 100.0, _round)
    except ValueError:
        print(f"警告: 无法解析百分比字符串 '{percentage_str}'")
        return 0


def get_cnbc_quote(symbol: str) -> Optional[Dict[str, Any]]:
    """
    从 CNBC 获取股票实时行情数据。

    参数:
        symbol (str): 股票代码，例如 'AAPL', 'GOOG', 'TSLA'

    返回:
        dict: 包含关键行情数据的字典，如果请求失败则返回 None。
              所有数值字段均为 float/int 类型，无百分比符号。
    """

    base_url = "https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol"

    params = {
        "symbols": symbol.upper(),
        "requestMethod": "itv",
        "noform": "1",
        "partnerId": "2",
        "fund": "1",
        "exthrs": "1",
        "output": "json",
        "events": "1"
    }

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Referer": "https://www.cnbc.com/"
    }

    try:
        response = requests.get(base_url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()

        # 检查是否有返回结果
        if not data.get("FormattedQuoteResult") or not data["FormattedQuoteResult"].get("FormattedQuote"):
            print(f"未找到股票代码: {symbol}")
            return None

        quotes = data["FormattedQuoteResult"]["FormattedQuote"]

        if isinstance(quotes, list) and len(quotes) > 0:
            quote = quotes[0]
        elif isinstance(quotes, dict):
            quote = quotes
        else:
            return None

        if quote.get('code') == 1:
            print(f"未找到股票代码: {symbol}")
            return None

        # --- 数据提取与清洗 ---
        # 基础信息
        symbol_clean = quote.get("symbol", symbol)
        name = quote.get("name", "")
        last_price = float(quote.get("last", 0).replace(',', ''))
        change = float(quote.get("change", 0))
        change_pct_raw = quote.get("change_pct", "0%")
        change_pct = parse_percentage(change_pct_raw)  # 转换为小数
        currency = quote.get("currencyCode", "USD")

        # 交易数据
        open_price = float(quote.get("open", 0).replace(',', ''))
        high_price = float(quote.get("high", 0).replace(',', ''))
        low_price = float(quote.get("low", 0).replace(',', ''))
        volume_raw = quote.get("volume", "0")
        volume_alt = quote.get("volume_alt", "0")
        volume = int(volume_raw.replace(',', '')) if volume_raw != "" else 0
        previous_close = float(quote.get("previous_day_closing", 0).replace(',', ''))

        # 财务指标
        pe_ratio = float(quote.get("pe", 0)) if quote.get("pe") != "" else None
        eps = float(quote.get("eps", 0)) if quote.get("eps") != "" else None
        fpe_ratio = float(quote.get("fpe", 0)) if quote.get("fpe") != "" else None
        feps = float(quote.get("feps", 0)) if quote.get("feps") != "" else None
        psales = float(quote.get("psales", 0)) if quote.get("psales") != "" else None
        market_cap_view = quote.get("mktcapView", "")
        market_cap_numeric = parse_financial_value(market_cap_view)

        # 分红与风险指标
        beta = float(quote.get("beta", 0)) if quote.get("beta") != "" else None

        # 盈利能力指标
        roe_ttm_raw = quote.get("ROETTM", "")
        roe_ttm = parse_percentage(roe_ttm_raw)  # 转换为小数
        net_profit_margin_ttm_raw = quote.get("NETPROFTTM", "")
        net_profit_margin_ttm = parse_percentage(net_profit_margin_ttm_raw)  # 转换为小数
        gross_margin_ttm_raw = quote.get("GROSMGNTTM", "")
        gross_margin_ttm = parse_percentage(gross_margin_ttm_raw)  # 转换为小数

        cleaned_data = {
            "symbol": symbol_clean,
            "name": name,
            "currency": currency,

            "price": {
                "current": last_price,
                "previous_close": previous_close,
                "open": open_price,
                "high": high_price,
                "low": low_price,
                "change": change,
                "change_percent_decimal": change_pct,  # 现在是小数
            },

            "volume": {
                "raw": volume,
                "formatted": volume_alt,
            },

            "valuation": {
                "pe_ttm": pe_ratio,
                "forward_pe": fpe_ratio,
                "eps": eps,
                "forward_eps": feps,
                "psales": psales,
                "market_cap_formatted": market_cap_view,
                "market_cap_numeric": market_cap_numeric,
            },

            "beta": beta,

            "profitability": {
                "roe_ttm_decimal": roe_ttm,  # 现在是小数
                "net_profit_margin_ttm_decimal": net_profit_margin_ttm,  # 现在是小数
                "gross_margin_ttm_decimal": gross_margin_ttm,  # 现在是小数
            },

            "raw_data": quote
        }

        return cleaned_data

    except requests.exceptions.RequestException as e:
        print(f"网络请求错误: {e}")
        return None
    except ValueError as e:
        print(f"JSON 解析或数据转换错误: {e}")
        return None
    except Exception as e:
        print(f"发生未知错误: {e}")
        return None


import requests
from bs4 import BeautifulSoup
from typing import Dict, List, Optional


def fetch_cnbc_profile(symbol: str = "AAPL") -> Dict:
    """
    从 CNBC 获取公司简介数据。
    注意：CNBC 有反爬机制，必须设置 Headers。如果数据是纯 JS 渲染，此方法可能获取不到完整内容。
    """
    url = f"https://www.cnbc.com/quotes/{symbol}"

    # 伪装成 Chrome 浏览器，防止被屏蔽
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.google.com/",
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return parse_company_html(response.text)

    except requests.exceptions.RequestException as e:
        print(f"请求失败: {e}")
        return {}


def parse_company_html(html_content: str) -> Dict:
    """解析 HTML 内容 (复用之前的逻辑)"""

    soup = BeautifulSoup(html_content, 'lxml')
    container = soup.find('div', class_='CompanyProfile-container')

    data = {
        "summary": "",
        "officers": [],
        "address": {},
        "website": ""
    }

    if not container:
        # 尝试备用选择器，有时类名会微调
        # CNBC 有时会将内容放在 id="QuotePage-layout-" 相关的结构中
        # 这里做一个简单的 fallback 检查
        # print("未找到 .CompanyProfile-container，尝试查找其他可能的结构...")
        # 可以在这里添加更多 fallback 逻辑
        return data

    # 1. Summary
    summary_div = container.find('div', class_='CompanyProfile-summary')
    if summary_div:
        span_tag = summary_div.find('span')
        data["summary"] = span_tag.get_text(strip=True) if span_tag else summary_div.get_text(strip=True)

    # 2. Officers
    for block in container.find_all('div', class_='CompanyProfile-officer'):
        divs = block.find_all('div', recursive=False)
        if len(divs) >= 2:
            data["officers"].append({
                "name": divs[0].get_text(strip=True),
                "title": divs[1].get_text(strip=True)
            })

    # 3. Address
    addr_block = container.find('div', class_='CompanyProfile-address')
    if addr_block:
        lines = [d.get_text(strip=True) for d in addr_block.find_all('div', recursive=False) if
                 'Header' not in d.get('class', [])]
        # 过滤掉空行
        lines = [l for l in lines if l]
        if len(lines) >= 4:
            data["address"] = {
                "street": lines[0], "city_state": lines[1], "zip": lines[2], "country": lines[3],
                "full": ", ".join(lines)
            }
        else:
            data["address"] = {"full": ", ".join(lines)}

    # --- 修正后的 Website 提取逻辑 ---
    website_div = container.find('div', class_='CompanyProfile-websiteLink')
    if website_div:
        link_tag = website_div.find('a')
        if link_tag and link_tag.get('href'):
            raw_url = link_tag['href'].strip()
            # 调用清洗函数
            data["website"] = clean_website_url(raw_url)
        else:
            # 备用：如果没有 a 标签，尝试清洗 div 文本
            text_url = website_div.get_text(strip=True)
            data["website"] = clean_website_url(text_url)

    return data


def clean_website_url(raw_url: str) -> str:
    """
    清洗 URL，只保留 'www.example.com' 格式。
    去除协议 (http/https)、路径、参数，并强制保留 www. (如果原域名有)。
    如果原域名没有 www (例如 apple.com)，则保留原样。
    """
    if not raw_url:
        return ""

    # 1. 解析 URL
    parsed = urlparse(raw_url)
    domain = parsed.netloc or parsed.path  # 如果没有 netloc，尝试从 path 获取（防止输入只是 'www.apple.com' 没有协议）

    # 2. 如果解析后仍然为空，直接返回空
    if not domain:
        return ""

    # 3. 去除端口号 (如果有，例如 www.apple.com:80)
    domain = domain.split(':')[0]

    # 4. 核心逻辑：只保留域名部分
    # 如果用户想要强制加上 www. (即使原链接没有)，可以取消下面注释
    # if not domain.startswith('www.'):
    #     domain = f"www.{domain}"

    # 根据你的要求 "只取里面的 www.apple.com"，我们假设输入通常包含 www。
    # 如果输入是 https://apple.com (没有www)，下面的逻辑会返回 apple.com。
    # 如果你必须强制返回带 www 的格式，请使用上面的注释代码。

    return domain

# --- 使用示例 ---
if __name__ == "__main__":

    result = fetch_cnbc_profile("COIN")

    if result:
        import json
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("未能提取到数据。如果 CNBC 更新了结构或加强了反爬，请使用方案二 (Selenium)。")

    # symbol_to_check = "ASML"
    #
    # print(f"正在获取 {symbol_to_check} 的数据...\n")
    # data = get_cnbc_quote(symbol_to_check)
    # # del data['raw_data']
    #
    # print(data)
    # print()
    #
    # if data:
    #     print(f"公司名称: {data['name']}")
    #     print(f"当前价格: {data['price']['current']} {data['currency']}")
    #     print(f"涨跌额: {data['price']['change']}")
    #     print(f"涨跌幅 (小数): {data['price']['change_percent_decimal']:.4f}")  # 以小数形式打印
    #     print(f"涨跌幅 (%): {(data['price']['change_percent_decimal'] or 0) * 100:.5f}%")  # 转回百分比形式便于阅读
    #     print(f"当日开盘: {data['price']['open']}")
    #     print(f"当日最高: {data['price']['high']}")
    #     print(f"当日最低: {data['price']['low']}")
    #     print(f"成交量: {data['volume']['raw']:,} ({data['volume']['formatted']})")
    #     print(f"市盈率 (TTM): {data['valuation']['pe_ttm']}")
    #     print(f"前瞻市盈率: {data['valuation']['forward_pe']}")
    #     print(f"市值: {data['valuation']['market_cap_formatted']} ({data['valuation']['market_cap_numeric']:.2e} USD)")
    #     print(f"Beta系数: {data['beta']}")
    #     print(f"净资产收益率 (TTM) (小数): {data['profitability']['roe_ttm_decimal']:.4f}")  # 以小数形式打印
    #     print(f"净资产收益率 (TTM) (%): {(data['profitability']['roe_ttm_decimal'] or 0) * 100:.2f}%")  # 转回百分比形式便于阅读
    #
    # else:
    #     print(f"获取 {symbol_to_check} 数据失败。")
