"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

"""
舆情数据
https://gushitong.baidu.com/stock/ab-600686?code=600686&financeType=stock&market=ab&name=%E9%87%91%E9%BE%99%E6%B1%BD%E8%BD%A6&subTab=2
"""

import requests, re
from bs4 import BeautifulSoup

headers_baidu = {
    'Host': 'finance.pae.baidu.com',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:136.0) Gecko/20100101 Firefox/136.0',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2',
    'Accept-Encoding': 'gzip, deflate, br, zstd',
    'Connection': 'keep-alive'
}

headers_cfi = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:136.0) Gecko/20100101 Firefox/136.0',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2',
    'Accept-Encoding': 'gzip, deflate, br, zstd',
    'Connection': 'keep-alive',
    'Referer': 'https://data.cfi.cn/data_ndkA0A1934A1935A5015.html',
    'Cookie': 'ASP.NET_SessionId=qxcr4qdtyiay0prj0k4iwrxp',
    'Host': 'data.cfi.cn'
}

headers_etnet = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:136.0) Gecko/20100101 Firefox/136.0',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2',
    'Accept-Encoding': 'gzip, deflate, br, zstd',
    'Connection': 'keep-alive',
    'Referer': 'https://www.cnyes.com/hkstock/quote/01876',
    'Host': 'www.cnyes.com'
}

def get_realtime_market_data_from_cfi(page=1):
    response = requests.post(
        f"https://data.cfi.cn/cfi_datacontent_server.aspx?ndk=A0A1934A1935A5015&client=pc",
        data={
            'search': 'all',
            'pageIndex': page,
            'sortCol': '',
            'subvalue': ''
        },
        headers=headers_cfi,
        timeout=5)

    results = parse_stock_html_to_dict(response.text)

    results = convert_chinese_keys_to_english(results)

    return results

def get_realtime_market_data_from_etnet_hk(code: str):
    """
    https://content.etnet.com.hk/content/cnyes/tc/stocks/delayed/quote.php?code=1
    https://content.etnet.com.hk/content/cnyes/tc/stocks/delayed/quote.php?code=01876
    """
    _url = f"https://content.etnet.com.hk/content/cnyes/tc/stocks/delayed/quote.php?code={code}"
    response = requests.get(_url, headers=headers_etnet, timeout=5)
    soup = BeautifulSoup(response.text, 'html.parser')

    FIELD_MAPPING = {
        '當前價格': 'close',
        '最高': 'high',
        '最低': 'low',
        '開市': 'open',
        '前收市': 'prev_close',
        '成交股數': 'volume',
        '成交額': 'turnover',
        '市值': 'market_cap',
        '1個月最高': 'high_1m',
        '1個月最低': 'low_1m',
        '賣空金額': 'short_sell_turnover',
        '市盈率': 'pe_ratio',
        '息率': 'dividend_yield'
    }

    container = soup.find('div', id='StkDetailMainBox')
    if not container:
        return {}

    table = container.find('table')
    rows = table.find_all('tr')

    raw_data = {}

    # --- 提取主价格 ---
    main_cell = rows[0].find('td', rowspan=True) or rows[0].find('td')
    if main_cell:
        price_span = main_cell.find('span', class_='Price')
        change_span = main_cell.find('span', class_='Change')

        current_price = price_span.get_text(strip=True) if price_span else "N/A"
        change_info_raw = change_span.get_text(strip=True) if change_span else ""

        raw_data['當前價格'] = current_price
        raw_data['漲跌信息'] = change_info_raw

    # --- 提取指标 ---
    all_metric_cells = table.find_all('td', class_='styleB')

    for cell in all_metric_cells:
        number_spans = cell.find_all('span', class_='Number')
        if not number_spans:
            continue

        value_str = number_spans[-1].get_text(strip=True)

        # 提取标签逻辑
        full_text = cell.get_text(separator=" ", strip=True)
        date_span = cell.find('span', class_='date')
        date_info = date_span.get_text(strip=True) if date_span else ""

        temp_text = full_text.replace(value_str, "").strip()
        if date_info:
            temp_text = temp_text.replace(date_info, "").strip()

        label_zh = re.sub(r'\s+', ' ', temp_text).strip()

        if date_info:
            label_zh = f"{label_zh} ({date_info})"

        if label_zh:
            raw_data[label_zh] = value_str

    # --- 转换阶段 ---
    final_data = {}

    for zh_key, raw_val in raw_data.items():
        base_key = zh_key.split(' (')[0].strip()
        suffix = ""
        if ' (' in zh_key:
            suffix = zh_key[zh_key.find(' ('):]

        # 特殊处理：漲跌信息
        if base_key == '漲跌信息':
            parsed_change = parse_change_info(raw_val)
            # 将解析出的两个值直接加入最终字典
            final_data['amplitude'] = parsed_change['change_value']
            final_data['chg_pct'] = parsed_change['change_percent']
            continue

        # 普通字段映射
        if base_key in FIELD_MAPPING:
            en_key_base = FIELD_MAPPING[base_key]
        else:
            en_key_base = f"unknown_{base_key}"

        en_key = en_key_base + suffix if suffix else en_key_base

        # 普通数值转换
        converted_val = _parse_number(raw_val)
        # 如果转换失败但原值是数字字符串（比如没有单位的纯数字），尝试直接转
        if converted_val is None and raw_val not in ["N/A", ""]:
            try:
                converted_val = float(raw_val.replace(',', ''))
            except:
                converted_val = raw_val  # 保留原值如果是文本

        final_data[en_key] = converted_val

    return final_data


def parse_change_info(change_str):
    """
    专门解析涨跌信息字符串，例如 "-0.110 (-1.392%)"
    返回字典: {'change_value': float, 'change_percent': float}
    """
    result = {
        'change_value': None,
        'change_percent': None
    }

    if not change_str:
        return result

    # 正则表达式匹配：可选的负号，数字，可选的小数部分，空格，(可选的负号，数字，%，)
    # 模式：(-?\d+\.?\d*)\s*\((-?\d+\.?\d*)%\)
    pattern = r"(-?\d+\.?\d*)\s*\((-?\d+\.?\d*)%\)"
    match = re.search(pattern, change_str)

    if match:
        try:
            result['change_value'] = float(match.group(1))
            result['change_percent'] = float(match.group(2))
        except ValueError:
            pass

    return result

def _parse_number(value_str):
    """
    将带有单位 (M, B) 和千分位的字符串转换为浮点数。
    如果无法转换，返回原始字符串。
    """
    if not value_str:
        return None

    # 去除首尾空格
    val = value_str.strip()

    # 检查是否包含非数字字符（除了 . , - M B）
    # 如果是像 "-0.110 (-1.392%)" 这样的复合字符串，不适合直接转 float，返回原串
    if '(' in val or '%' in val:
        return val

    multiplier = 1
    if val.upper().endswith('M'):
        multiplier = 10 ** 6
        val = val[:-1]
    elif val.upper().endswith('B'):
        multiplier = 10 ** 9
        val = val[:-1]

    # 移除千分位逗号
    val = val.replace(',', '')

    try:
        return float(val) * multiplier
    except ValueError:
        return value_str  # 如果转换失败，返回原始字符串

def get_company_profile_from_cfi(code: str):
    """
    获取个股基本信息
    """
    """
    https://quote.cfi.cn/quote.aspx?actstockid=&actcontenttype=gsda&client=pc&searchcode=688599&x=0&y=0
    """
    response = requests.get(f"https://quote.cfi.cn/quote.aspx?actstockid=&actcontenttype=gsda&client=pc&searchcode={code}&x=0&y=0", headers=headers_cfi, timeout=5)
    _info = _extract_company_info(html_content=response.text)
    return _info


def _extract_company_info(html_content):

    # 解析 HTML
    soup = BeautifulSoup(html_content, 'html.parser')

    # 找到所有表格行
    rows = soup.find_all('tr')

    info_dict = {}

    for row in rows:
        cols = row.find_all('td')
        if len(cols) < 2:
            continue

        # 获取键（去除可能的多余空格或换行）
        key = cols[0].get_text(strip=True)
        value = cols[1].get_text(strip=True)

        # 清理键名（如去除“*”或其他符号，如果有的话）
        key = re.sub(r'[\*\s]+$', '', key)

        # 映射常用字段为更清晰的键名（可选）
        key_mapping = {
            '公司中文名称': 'company_name',
            '股票代码': 'stock_code',
            '成立日期': 'establish_date',
            '注册资本/万元': 'registered_capital',
            '法人代表': 'legal_representative',
            '公司简介': 'company_introduction',
            '经营范围': 'business_scope',
            '主营业务': 'main_business',
            '证监会行业(新)': 'industry',
            '省份': 'province',
            '城市': 'city',
            '区县信息': 'district',
            '注册地址': 'registered_address',
            '办公地址': 'office_address',
            '公司电话': 'company_phone',
            '公司传真': 'company_fax',
            '公司电子邮件地址': 'email',
            '公司网址': 'website',
            '董事会秘书电话': 'board_secretary_phone',
            '信息披露人': 'information_disclosure_person',
            '实际控制人': 'actual_controller',
            '公司独立董事(现任)': 'independent_directors',
            '审计机构': 'auditor',
            '律师事务所': 'law_firm',
            '证券事务代表': 'securities_representative',
        }

        if key in key_mapping:
            clean_key = key_mapping[key]
            info_dict[clean_key] = value

    return info_dict

def get_stock_market_data_from_cfi(code: str):
    """
    https://quote.cfi.cn/quote_600905.html
    """
    response = requests.get(f"https://quote.cfi.cn/quote_{code}.html", headers=headers_cfi, timeout=5)

    # 解析HTML
    soup = BeautifulSoup(response.text, 'html.parser')

    # 提取行情数据
    data = {}
    data['name'] = soup.find('div', class_='Lfont').text
    data['close'] = soup.find('td', class_='s_pclose').text.replace('↓', '').replace('↑', '')

    # 遍历表格中的每一行
    for row in soup.select('#quotetab_stock tr'):
        # 对于每一行中的每个单元格
        for cell in row.find_all('td'):
            # 清理文本并分割成键值对
            key_value = ''.join(cell.stripped_strings).split(':')
            if len(key_value) == 2:
                key, value = key_value
                value = re.sub(r'[^\d.]', '', value)
                data[key] = value

    # 中文到英文的映射
    translation_map = {
        'name': 'name',
        'close': 'close',
        '今开': 'open',
        '最高': 'high',
        '振幅': 'amplitude',
        '换手率': 'turnover_rate',
        '昨收': 'previous_close',
        '最低': 'low',
        '成交量': 'volume',
        '成交额': 'amount',
        '市盈率': 'pe_ratio',
        '扣除后市盈率': 'adjusted_pe_ratio',
        '市净率': 'pb_ratio'
    }

    # 翻译后的数据
    translated_data = {translation_map[key]: value for key, value in data.items() if key in translation_map}

    translated_data['code'] = code
    translated_data['name'] = re.sub(r'\([^)]*\)', '', translated_data['name'])
    translated_data['amount'] = float(translated_data['amount']) * 10000
    translated_data['volume'] = float(translated_data['volume'])
    translated_data['close'] = float(translated_data['close'])
    translated_data['open'] = float(translated_data['open'])
    translated_data['high'] = float(translated_data['high'])
    translated_data['low'] = float(translated_data['low'])
    translated_data['amplitude'] = float(translated_data['amplitude'])
    translated_data['turnover_rate'] = float(translated_data['turnover_rate'])
    translated_data['previous_close'] = float(translated_data['previous_close'])
    if translated_data['pe_ratio'] != '':
        translated_data['pe_ratio'] = float(translated_data['pe_ratio'])
    if translated_data['adjusted_pe_ratio'] != '':
        translated_data['adjusted_pe_ratio'] = float(translated_data['adjusted_pe_ratio'])
    translated_data['pb_ratio'] = float(translated_data['pb_ratio'])

    return translated_data


def get_realtime_market_data(code):
    """
    获取股票市盈率市净率
    https://finance.pae.baidu.com/vapi/v1/getquotation?srcid=5353&all=1&code=600686&query=600686&eprop=min&stock_type=ab&chartType=minute&group=quotation_minute_ab&finClientType=pc
    """
    url = "https://finance.pae.baidu.com/vapi/v1/getquotation"
    params = {
        'srcid': 5353,
        'all': 1,
        'code': code,
        'query': code,
        'eprop': 'min',
        'stock_type': 'ab',
        'chartType': 'minute',
        'group': 'quotation_minute_ab',
        'finClientType': 'pc'
    }
    response = requests.get(url, headers=headers_baidu, params=params)
    if response.status_code == 200:
        return response.json()
    else:
        response.raise_for_status()


def get_cn_index_data_from_sina():
    """
    https://money.finance.sina.com.cn/mkt/#dpzs
    """
    base_url = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeDataSimple"
    # 构建参数字典
    params = {
        'page': 1,
        'num': 80,
        'sort': 'symbol',
        'asc': 0,
        'node': 'dpzs',
        '_s_r_a': 'page',
    }
    response = requests.get(base_url, params=params)
    if response.status_code == 200:
        return response.json()
    else:
        response.raise_for_status()


def get_hk_index_data_from_sina():
    """
    @brief Fetch real-time Hong Kong stock index data from Sina Finance and return it as a list of dictionaries with snake_case English keys.
    @param: None
    @return: A list of dictionaries, where each dictionary represents an index with snake_case English keys.
    @rtype: list[dict]
    @throws:
        - requests.exceptions.RequestException: If the HTTP request fails.
        - ValueError: If the response is empty or cannot be parsed correctly.
    @example:
        index_data = get_hk_index_data_from_sina()
        for item in index_data:
            print(item)
    """
    url = (
        "https://hq.sinajs.cn/rn=mtf2t&list=hkCES100,hkCES120,hkCES280,hkCES300,hkCESA80,hkCESG10,"
        "hkCESHKM,hkCSCMC,hkCSHK100,hkCSHKDIV,hkCSHKLC,hkCSHKLRE,hkCSHKMCS,hkCSHKME,hkCSHKPE,hkCSHKSE,"
        "hkCSI300,hkCSRHK50,hkGEM,hkHKL,hkHSCCI,hkHSCEI,hkHSI,hkHSMBI,hkHSMOGI,hkHSMPI,hkHSTECH,hkSSE180,"
        "hkSSE180GV,hkSSE380,hkSSE50,hkSSECEQT,hkSSECOMP,hkSSEDIV,hkSSEITOP,hkSSEMCAP,hkSSEMEGA,hkVHSI"
    )
    headers = {"Referer": "https://vip.stock.finance.sina.com.cn/"}
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise RuntimeError("Failed to fetch data from Sina Finance.") from e
    data_text = response.text
    # 提取有效数据部分
    data_list = [
        item.split('"')[1].split(",")  # 保留双引号后的内容并按逗号分割
        for item in data_text.split("\n") if len(item.split('"')) > 1
    ]
    if not data_list:
        raise ValueError("The response contains no valid index data.")
    # 定义小写英文列名映射（中文 -> snake_case 英文）
    column_rename_map = {
        "代码": "symbol",
        "名称": "name",
        "今开": "open",
        "昨收": "prev_close",
        "最高": "high",
        "最低": "low",
        "最新价": "latest",
        "涨跌额": "change",
        "涨跌幅": "change_percentage"
    }
    # 定义最终保留的列名
    selected_columns = [
        "symbol", "name", "latest", "change", "change_percentage", "prev_close", "open", "high", "low"
    ]
    # 构建最终的字典数组
    result = []
    for row in data_list:
        row_dict = {
            "symbol": row[0],
            "name": row[1],
            "open": float(row[2]) if row[2] else None,
            "prev_close": float(row[3]) if row[3] else None,
            "high": float(row[4]) if row[4] else None,
            "low": float(row[5]) if row[5] else None,
            "latest": float(row[6]) if row[6] else None,
            "change": float(row[7]) if row[7] else None,
            "change_percentage": float(row[8]) if row[8] else None,
        }
        # 只保留指定字段
        result.append({
            col: row_dict[col]
            for col in selected_columns
            if col in row_dict
        })
    return result


def get_hk_market_data_from_sina(page=1, pagesize=100):
    """
    https://money.finance.sina.com.cn/mkt/#sgt_hk
    """
    base_url = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHKStockData"
    # 构建参数字典
    params = {
        'page': page,
        'num': pagesize,
        'sort': 'symbol',
        'asc': 0,
        'node': 'sgt_hk',
        '_s_r_a': 'page',
    }
    response = requests.get(base_url, params=params)
    if response.status_code == 200:
        return response.json()
    else:
        response.raise_for_status()


def get_cn_market_data_from_sina(page=1, pagesize=100):
    """
    https://money.finance.sina.com.cn/mkt/#stock_hs_up
    """
    base_url = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
    # 构建参数字典
    params = {
        'page': page,
        'num': pagesize,
        'sort': 'symbol',
        'asc': 0,
        'node': 'hs_a',
        '_s_r_a': 'page',
    }
    response = requests.get(base_url, params=params)
    if response.status_code == 200:
        stocks = response.json()
        return stocks
    else:
        response.raise_for_status()


def get_baidu_hotrank_list(page=0, page_size=10, day='20250319', hour='21', market='ab'):
    base_url = "https://finance.pae.baidu.com/vapi/v1/hotrank"
    # 构建参数字典
    params = {
        'dsp': 'iphone',
        'product': 'stock',
        'day': day,
        'hour': hour,
        'pn': page,
        'rn': page_size,
        'market': market,
        'type': 'hour',
        'finClientType': 'pc'
    }
    response = requests.get(base_url, headers=headers_baidu, params=params)
    if response.status_code == 200:
        return response.json()
    else:
        response.raise_for_status()


def get_baidu_stock_list(sort_type=1, sort_key=14, from_mid=1, pn=0, rn=20, group='ranklist', market='ab',
                         fin_client_type='pc'):
    url = "https://finance.pae.baidu.com/selfselect/getmarketrank"
    params = {
        'sort_type': sort_type,
        'sort_key': sort_key,
        'from_mid': from_mid,
        'pn': pn,
        'rn': rn,
        'group': group,
        'type': market,
        'finClientType': fin_client_type
    }
    response = requests.get(url, headers=headers_baidu, params=params)
    if response.status_code == 200:
        return response.json()
    else:
        response.raise_for_status()


def get_rising_and_falling_count_from_cfi():
    """
    https://quote.cfi.cn/data_ndkA0A1934A1935A58.html#A0A1934A1935
    https://quote.cfi.cn/cfi_datacontent_server.aspx?ndk=A0A1934A1935A58&client=pc
    """
    response = requests.post(f"https://quote.cfi.cn/cfi_datacontent_server.aspx?ndk=A0A1934A1935A58&client=pc",
                             timeout=5)
    # 解析HTML
    soup = BeautifulSoup(response.text, 'html.parser')

    table = soup.find('table', class_='table_data')
    rows = table.find_all('tr')[1:]  # 跳过表头
    data = {}
    for row in rows:
        cols = row.find_all('td')
        if len(cols) == 2:
            data[cols[0].text.strip()] = int(cols[1].text.strip())
    # 中文到英文的映射
    translation_map = {
        '上涨': 'rising',
        '涨停': 'limit_up',
        '下跌': 'falling',
        '跌停': 'limit_down',
        '平盘': 'flat'
    }
    # 翻译后的数据
    translated_data = {translation_map[key]: value for key, value in data.items() if key in translation_map}

    # 涨跌停板加入到数据里面去
    translated_data['rising'] += translated_data['limit_up']
    translated_data['falling'] += translated_data['limit_down']

    return translated_data


def parse_stock_html_to_dict(html_content):
    """
    解析HTML表格，将数据转换为字典列表，并尝试将数值字段转换为浮点数。

    参数:
        html_content (str): 包含表格的HTML文本

    返回:
        list: 字典列表，每个字典代表一只股票的数据。
              例如: [{'代码': '300912', '股票名称': '凯龙高科', '最新': 34.3, ...}, ...]
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    table = soup.find('table', class_='table_data')

    if not table:
        print("未找到目标表格。")
        return []

    data_list = []
    headers = []
    rows = table.find_all('tr')

    for i, row in enumerate(rows):
        cols = row.find_all(['td', 'th'])
        if not cols:
            continue

        # 清洗文本：去除多余空白字符
        texts = [re.sub(r'\s+', ' ', col.get_text(strip=True)) for col in cols]

        # 第一行通常是表头
        if i == 0:
            headers = texts
            continue

        # 确保数据列数与表头一致（防止表格结构异常）
        if len(texts) != len(headers):
            # 如果列数不匹配，用空字符串填充或截断
            # 这里简单处理，实际应用中可根据日志记录异常
            texts += [''] * (len(headers) - len(texts))

        # 创建字典并进行类型转换
        row_dict = {}
        for key, value in zip(headers, texts):
            # 去除字段名两端的空格
            key = key.strip()
            # 去除值两端的空格
            clean_value = value.strip()

            # --- 核心优化：智能类型转换 ---
            converted_value = convert_value(clean_value, key)
            row_dict[key] = converted_value

        data_list.append(row_dict)

    return data_list


def convert_value(value_str, field_name):
    """
    根据字段名或值的内容，尝试将字符串转换为合适的数值类型。

    参数:
        value_str (str): 要转换的字符串
        field_name (str): 字段名称（用于判断单位）

    返回:
        int/float/str: 转换后的值
    """
    # 如果字符串为空，直接返回 None 或 0，这里返回 0.0 方便计算
    if not value_str or value_str == '-':
        # 对于成交量/成交额等，空值可能是0；对于价格，可能是NaN。
        # 这里简单返回 0.0，实际应用中可根据 field_name 区分
        return 0.0

        # --- 针对特定字段的预处理 ---
    # 1. 处理带百分号的字段 (涨跌幅%, 换手率%)
    if '%' in field_name or value_str.endswith('%'):
        value_str = value_str.rstrip('%')
        try:
            return float(value_str)
        except ValueError:
            return value_str  # 转换失败保留原字符串

    # 2. 处理成交量/成交额单位 (将 '万', '亿' 转换为数字)
    # 注意：你的文档中成交量单位是“手”(通常1手=100股)，成交额单位是“万元”
    if '成交额' in field_name:
        # 假设数据已经是“万元”为单位的数字字符串
        try:
            # 直接转为浮点数，单位保持为“万元”
            return float(value_str)
        except ValueError:
            return value_str
    elif '成交量' in field_name:
        # 假设数据是“手”为单位
        try:
            return float(value_str)
        except ValueError:
            return value_str

    # 3. 处理市盈率 (有些可能是负数或 '--')
    if '市盈率' in field_name:
        try:
            return float(value_str)
        except ValueError:
            return float('nan')  # 或者返回 None

    # --- 通用数值转换 ---
    # 尝试转换为浮点数（处理正负号）
    # 正则表达式移除非数字字符（保留 - . 数字），但要小心负号在末尾的情况（如 10.00-）
    # 简单处理：如果以 - 结尾，说明是负数
    temp_val = value_str
    if temp_val.endswith('-'):
        temp_val = '-' + temp_val.rstrip('-')

    try:
        # 移除千分位逗号（虽然你的数据似乎没有逗号，但为了健壮性）
        temp_val = temp_val.replace(',', '')
        return float(temp_val)
    except ValueError:
        # 转换失败，保留为字符串 (如股票名称、代码)
        return value_str

    # --- 特殊字段：代码/名称 保持字符串 ---


def convert_chinese_keys_to_english(data_list):
    """
    将包含中文键名的字典列表转换为英文键名。

    参数:
        data_list (list): 包含中文字段字典的列表

    返回:
        list: 包含英文字段字典的列表
    """
    # 定义映射关系
    key_mapping = {
        '代码': 'code',
        '股票名称': 'name',
        '最新': 'close',
        '涨跌': 'change',
        '涨跌幅%': 'change_percent',
        '前收': 'prev_close',
        '开盘': 'open',
        '最高': 'high',
        '最低': 'low',
        '成交量/手': 'volume_hand',
        '成交额/万元': 'amount_wyuan',
        '市盈率/倍': 'pe_ratio',
        '换手率%': 'turnover_rate',
        '总股本/亿': 'total_shares_yi',
        '流通股本/亿': 'float_shares_yi'
    }

    english_data = []
    for item in data_list:
        new_item = {}
        for zh_key, value in item.items():
            if zh_key in key_mapping:
                en_key = key_mapping[zh_key]
                new_item[en_key] = value
            else:
                # 如果遇到未定义的键（如数据源新增了字段），可以选择保留原键或忽略
                new_item[zh_key.lower()] = value
        english_data.append(new_item)

    return english_data


if __name__ == '__main__':

    # data = get_rising_and_falling_count_from_cfi()
    # print(data)

    # data = get_stock_market_data_from_cfi(code='300843')
    # print(data)

    # data = get_realtime_market_data_from_cfi(page=2)
    # print(data)

    data = get_company_profile_from_cfi(code='300866')
    print(data)
