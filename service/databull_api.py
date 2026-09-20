"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from typing import Optional, Union, Dict, Any
from urllib.parse import urljoin
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import pandas as pd
import requests

class DataBull:
    """
    金融数据 API 客户端封装。支持 AlphaLom 标准接口调用，内置连接池、统一异常处理与 DataFrame 自动转换。
    注意：需安装依赖：pip install pandas requests
    """
    def __init__(self, api_key: str, base_url: Optional[str] = None) -> None:
        self.base_url = (base_url or "https://api.databull.cn").rstrip("/")
        self.session = self._build_session()
        self.session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json"
        })

    def _build_session(self):
        session = requests.Session()

        # 放大连接池（按实际并发需求调整）
        adapter = HTTPAdapter(
            pool_connections=30,
            pool_maxsize=30
        )
        session.mount("https://", adapter)
        session.mount("http://", adapter)

        # 配置重试策略（防金融接口限流/瞬时丢包）
        retry = Retry(
            total=3,
            backoff_factor=1,  # 指数退避：1s -> 2s -> 4s
            status_forcelist=[429, 500, 502, 503, 504],
            raise_on_status=False
        )
        session.mount("https://", HTTPAdapter(max_retries=retry))

        return session

    def _request(self, endpoint: str, params: Optional[Dict] = None) -> Any:
        """内部统一 HTTP GET 请求方法"""
        url = urljoin(self.base_url + "/", endpoint.lstrip("/"))
        try:
            resp = self.session.get(url, params=params, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.Timeout:
            print(f"{endpoint}, 请求超时")
        except requests.exceptions.HTTPError as e:
            print(f"{endpoint}, HTTP {resp.status_code}: {resp.text}")
        except requests.exceptions.ConnectionError:
            print(f"{endpoint}, 网络连接失败")
        except ValueError as e:
            print(f"{endpoint}, JSON 解析异常: ")
        except Exception as e:
            print(f"{endpoint}, 未知请求异常: {e}")
        return None

    @staticmethod
    def _to_dataframe(data: Any, date_col: str = "date"):
        """将 JSON 结果安全转换为带日期索引的 DataFrame"""
        if not data or (isinstance(data, dict) and len(data) == 0):
            return None

        if isinstance(data, (list, dict)):
            df = pd.DataFrame(data)
            if df.empty:
                return None
            if date_col in df.columns:
                df[date_col] = pd.to_datetime(df[date_col])
                df.set_index(date_col, inplace=True)
            return df
        return None

    def get_market_sector(self, sector_type: str = "sw1", market: str = "cn") -> Optional[Union[list, dict]]:
        """获取行业/概念板块分类列表"""
        return self._request(f"{market}/market/sector_data/{sector_type}")

    def get_etf_list(self, market: str = "cn", search: Optional[str] = None, exchange: Optional[str] = None) -> Optional[Union[list, dict]]:
        """获取 ETF 基金清单（可按关键词 search 或交易所 exchange 过滤）

        search 映射到文档的 q 参数：按 ETF 代码或名称模糊匹配（大小写不敏感）；
        exchange 为 SH/SZ。文档要求路径以 / 结尾（不带尾斜杠会收到 307 跳转），
        搜索联想调用频繁，这里带上尾斜杠省掉一次重定向往返。
        """
        params = {}
        if search:
            params["q"] = search
        if exchange:
            params["exchange"] = exchange
        return self._request(f"{market}/etfs/", params=params or None)

    def get_etf_composition(self, symbol: str, market: str = "cn") -> Optional[Union[list, dict]]:
        """获取 ETF 成分股构成（component_code / component_name 列表）

        注：实测上游接口路径为 /{market}/etfs/etf_composition，旧路径
        /{market}/etf_composition 会 404 导致成分股恒为空。这里先走实测正确的
        路径，失败时再回退旧路径，两条路径都能兜住，并与 get_etf_info 一致
        只回传 data 数组。
        """
        res = self._request(f"{market}/etfs/etf_composition", params={"symbol": symbol})
        if res is None:
            res = self._request(f"{market}/etf_composition", params={"symbol": symbol})
        return res.get("data") if isinstance(res, dict) else res

    def get_etf_info(self, symbol: str, market: str = "cn") -> Optional[Dict]:
        """获取单只 ETF 基本资料（名称、交易所、净值、申赎单位、类型、申赎开关、交易日等）"""
        res = self._request(f"{market}/etfs/info", params={"symbol": symbol})
        return res.get("data") if isinstance(res, dict) else res

    def get_stock_list(self, market: str = "cn", search: str = None, exchange: str = None) -> Optional[Union[list, dict]]:
        """获取标的资产/股票全量清单（支持搜索：search 关键词、exchange 交易所 SH/SZ）"""
        params = {}
        if search:
            params["q"] = search
        if exchange:
            params["exchange"] = exchange
        return self._request(f"{market}/stocks", params=params or None)

    def get_company(self, symbol: str, market: str = "cn") -> Optional[Dict]:
        """获取公司基础资料 / 个股 Profile"""
        res = self._request(f"{market}/stock/profile", params={"symbol": symbol})
        return res.get("data") if isinstance(res, dict) else res

    def get_stock_info(self, symbol: str, market: str = "cn") -> Optional[Union[list, dict]]:
        """获取个股实时基础信息"""
        return self._request(f"{market}/stock/info", params={"symbol": symbol})

    def get_last_tick(self, symbol: str, tick_type: str = "stock", market: str = "cn") -> Optional[Union[list, dict]]:
        """获取最新Tick或日内分时行情"""
        return self._request(f"{market}/stock/tick", params={"symbol": symbol, "tick_type": tick_type})

    def get_index_history(self, index_code: str, start_date: str, end_date: str, market: str = "cn"):
        """获取指数历史行情 (日线)"""
        data = self._request(f"{market}/index/history", params={
            "index_code": index_code, "start_date": start_date, "end_date": end_date
        })
        return self._to_dataframe(data.get("data") if isinstance(data, dict) else data)

    def get_market_fear_greed(self, index_code: str, start_date: str, end_date: str, market: str = "cn"):
        """获取指数恐惧与贪婪数据 (日线)"""
        data = self._request(f"{market}/market/fear_greed", params={
            "index_code": index_code, "start_date": start_date, "end_date": end_date
        })
        return self._to_dataframe(data.get("data") if isinstance(data, dict) else data)

    def get_history(self, symbol: str, start_date: str, end_date: str, period: str = "d", market: str = "cn"):
        """获取股票历史行情 (日线/分钟线)"""
        data = self._request(f"{market}/stock/history", params={
            "symbol": symbol, "start_date": start_date, "end_date": end_date, "period": period, "v": "1.0"
        })
        return self._to_dataframe(data.get("data") if isinstance(data, dict) else data)

    def get_etf_history(self, symbol: str, start_date: str, end_date: str, market: str = "cn"):
        """获取ETF历史净值/行情"""
        data = self._request(f"{market}/etf/history", params={
            "symbol": symbol, "start_date": start_date, "end_date": end_date
        })
        return self._to_dataframe(data.get("data") if isinstance(data, dict) else data)

    def get_stock_financial_data(self, symbol: str, start_date: str, end_date: str, report_type: str) -> Optional[Union[list, dict]]:
        """获取上市公司财务指标数据（按公告日期区间倒序返回）

        report_type 取值（据上游 OpenAPI）：Balance 资产负债表 / Income 利润表 /
        CashFlow 现金流量表 / Capital 资本结构，文档默认 Balance。另外 PershareIndex
        （主要财务指标）文档未列出但**实测可用**，fundamental_service 与 DCF 研报的
        计算全部依赖它。**故意不给默认值**：报表类型不同，report_table 的字段也不同，
        静默取默认值会让下游算出错误的基本面评分。

        start_date / end_date 为公告日期区间，上游同时接受 YYYYMMDD 与 YYYY-MM-DD。
        """
        return self._request("cn/stock/financial_data", params={
            "symbol": symbol, "start_date": start_date, "end_date": end_date, "report_type": report_type
        })
