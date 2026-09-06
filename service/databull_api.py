"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

import logging
from typing import Optional, Union, Dict, Any
from urllib.parse import urljoin

import pandas as pd
import requests

class DataBull:
    """
    金融数据 API 客户端封装。支持 FinFilo 标准接口调用，内置连接池、统一异常处理与 DataFrame 自动转换。
    注意：需安装依赖：pip install pandas requests
    """
    _LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"

    def __init__(self, api_key: str, base_url: Optional[str] = None) -> None:
        self.base_url = (base_url or "https://api.finfilo.com").rstrip("/")

        # 使用 Session 实现连接池复用，提升并发性能
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json"
        })

        # 配置标准日志系统（替代 print）
        logging.basicConfig(level=logging.INFO, format=self._LOG_FORMAT)
        self.logger = logging.getLogger(__name__)

    def _request(self, endpoint: str, params: Optional[Dict] = None) -> Any:
        """内部统一 HTTP GET 请求方法"""
        url = urljoin(self.base_url + "/", endpoint.lstrip("/"))
        try:
            resp = self.session.get(url, params=params, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.Timeout:
            self.logger.warning("请求超时")
        except requests.exceptions.HTTPError as e:
            self.logger.error(f"HTTP {resp.status_code}: {resp.text}")
        except requests.exceptions.ConnectionError:
            self.logger.error("网络连接失败")
        except ValueError as e:
            self.logger.error("JSON 解析异常: ", exc_info=e)
        except Exception as e:
            self.logger.exception(f"未知请求异常: {e}")
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

    def get_etf_list(self, market: str = "cn") -> Optional[Union[list, dict]]:
        """获取 ETF 基金清单"""
        return self._request(f"{market}/etfs")

    def get_etf_composition(self, symbol: str, market: str = "cn") -> Optional[Union[list, dict]]:
        """获取 ETF 成分股构成"""
        return self._request(f"{market}/etf_composition", params={"symbol": symbol})

    def get_stock_list(self, market: str = "cn") -> Optional[Union[list, dict]]:
        """获取标的资产/股票全量清单"""
        return self._request(f"{market}/stocks")

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
        """获取指数历史行情 (日线/分钟线)"""
        data = self._request(f"{market}/index/history", params={
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
        """获取上市公司财务指标数据"""
        return self._request("cn/stock/financial_data", params={
            "symbol": symbol, "start_date": start_date, "end_date": end_date, "report_type": report_type
        })